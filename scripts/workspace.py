#!/usr/bin/env python3
"""cubbie coding harness workspace engine: persistent projects with local git checkpoints.

Scaffolds student project workspaces inside Cubbie's sandbox from a bundled web
template, a GitHub repository URL, or a folder/zip in /workspace/your_files/.
File writes create automatic local git checkpoints that can be rolled back,
projects export as clean zips for iMessage delivery, and a feature branch can be
pushed to GitHub with a pull request created via GITHUB_TOKEN.

State lives under $SKILL_DATA_DIR or ~/.config/cubbie-coding-harness/ and survives
sandbox restarts. All stdout stays under 7,500 characters so Cubbie never loses
context or exit statuses.

Exit codes:
  0  ok
  2  bad arguments (missing flags, invalid project/template, workspace exists)
  3  project not found
  4  git operation failed (init, checkpoint, undo, branch)
  5  source import failed (missing folder or bad zip)
  6  git clone failed
  7  GITHUB_TOKEN not set (needed for pr)
  8  push or pull request failed
  9  zip export failed
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

OUTPUT_LIMIT = 7400
TREE_BUDGET = 2000
GIT_BUDGET = 900
EXCERPT_LINES = 12
EXCERPT_FILE_BUDGET = 1200
YOUR_FILES_DIR = Path("/workspace/your_files")
IGNORED_DIRS = {".git", "node_modules", "dist", "build", "__pycache__",
                ".pytest_cache", ".mypy_cache", ".cache", ".venv", "venv"}
SKIP_FILES = {".DS_Store"}
SOURCE_EXTS = {".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".py", ".json",
               ".md", ".txt", ".yaml", ".yml"}
TEMPLATES = ("modern-web", "react-spa")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SKILL_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = SKILL_ROOT / "assets" / "sample_data.json"


def emit(text: str) -> None:
    """Print stdout-safe text: ANSI stripped, hard output budget enforced."""
    text = ANSI_RE.sub("", text).rstrip("\n")
    if len(text) > OUTPUT_LIMIT:
        notice = "\n...[truncated to fit Cubbie's 7,500-character stdout limit]"
        text = text[: OUTPUT_LIMIT - len(notice)] + notice
    print(text)


def fail(message: str, code: int) -> None:
    emit(message)
    sys.exit(code)


def data_root() -> Path:
    return Path(os.environ.get("SKILL_DATA_DIR") or Path.home() / ".config" / "cubbie-coding-harness")


def workspace_path(project: str) -> Path:
    return data_root() / "workspaces" / project


def valid_project(name: str) -> bool:
    return bool(NAME_RE.match(name))


def load_state() -> dict:
    try:
        return json.loads((data_root() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def record_workspace(project: str, origin: str, remote: str | None) -> None:
    state = load_state()
    state.setdefault("workspaces", {})[project] = {
        "origin": origin,
        "remote": remote,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_state(state)


def git_env() -> dict:
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def git(ws: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ws), *args], capture_output=True,
                          text=True, env=git_env())


def identity_args(ws: Path) -> list[str]:
    email = git(ws, "config", "--get", "user.email")
    if email.returncode == 0 and email.stdout.strip():
        return []
    return ["-c", "user.name=cubbie coding harness",
            "-c", "user.email=cubbie-coding-harness@users.noreply.github.com"]


def ensure_git_repo(ws: Path) -> None:
    if (ws / ".git").is_dir():
        return
    r = git(ws, "init", "-b", "main")
    if r.returncode != 0:
        fail(f"git init failed: {r.stderr.strip() or r.stdout.strip()}", 4)


def run_checkpoint(ws: Path, message: str) -> str | None:
    """Stage all changes and commit; return the short hash, or None if clean."""
    status = git(ws, "status", "--porcelain")
    if status.returncode != 0:
        fail(f"git status failed: {status.stderr.strip()}", 4)
    if not status.stdout.strip():
        return None
    r = git(ws, "add", "-A")
    if r.returncode != 0:
        fail(f"git add failed: {r.stderr.strip()}", 4)
    r = git(ws, *identity_args(ws), "commit", "-m", message)
    if r.returncode != 0:
        fail(f"git commit failed: {r.stderr.strip() or r.stdout.strip()}", 4)
    return git(ws, "rev-parse", "--short", "HEAD").stdout.strip()


def changed_files(ws: Path) -> str:
    r = git(ws, "diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else ""


def iter_workspace_files(ws: Path):
    for root, dirs, files in os.walk(ws):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        for name in sorted(files):
            if name not in SKIP_FILES:
                yield Path(root) / name


def require_workspace(project: str) -> Path:
    if not valid_project(project):
        fail(f"invalid project name {project!r}: use letters, digits, '.', '_', '-'", 2)
    ws = workspace_path(project)
    if not ws.is_dir():
        fail(f"no workspace named '{project}' (init it first)", 3)
    return ws


def safe_relpath(path: str) -> bool:
    if not path or path.startswith(("/", "~")) or "\\" in path:
        return False
    parts = PurePosixPath(path).parts
    if not parts or ".." in parts or ":" in parts[0] or ".git" in parts:
        return False
    return True


def safe_zip_member(name: str) -> bool:
    if not name or name.startswith(("/", "\\", "~")):
        return False
    parts = PurePosixPath(name).parts
    if not parts or ".." in parts or ":" in parts[0]:
        return False
    return parts[0] not in (".git", "node_modules")


def tail(text: str, lines: int = 5) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


# ---------------------------------------------------------------- init

def init_template(project: str, ws: Path, template: str) -> None:
    tpl = SKILL_ROOT / "assets" / "templates" / template
    if not tpl.is_dir():
        fail(f"unknown template {template!r} (choose {' or '.join(TEMPLATES)})", 2)
    ws.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(tpl, ws)
    ensure_git_repo(ws)
    commit = run_checkpoint(ws, f"init: scaffold {project} from {template} template")
    record_workspace(project, f"template:{template}", None)
    count = sum(1 for _ in iter_workspace_files(ws))
    emit(f"initialized '{project}' from {template} at {ws}\n"
         f"files: {count}\n"
         f"checkpoint {commit or '-'}: init: scaffold {project} from {template} template")


def init_clone(project: str, ws: Path, url: str) -> None:
    if not url.startswith("https://"):
        fail("--repo must be an https:// GitHub URL", 2)
    ws.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["git", "clone", url, str(ws)], capture_output=True,
                       text=True, env=git_env())
    if r.returncode != 0:
        shutil.rmtree(ws, ignore_errors=True)
        fail(f"git clone failed:\n{tail(r.stderr, 3)}", 6)
    remote = git(ws, "remote", "get-url", "origin").stdout.strip() or url
    branch = git(ws, "branch", "--show-current").stdout.strip() or "(default)"
    head = git(ws, "log", "-1", "--oneline").stdout.strip()
    record_workspace(project, f"clone:{url}", remote)
    emit(f"cloned '{project}' from {remote}\nbranch: {branch}\nhead: {head}")


def extract_zip(src: Path, ws: Path) -> None:
    ws.parent.mkdir(parents=True, exist_ok=True)
    ws.mkdir(parents=True, exist_ok=True)
    skipped = 0
    try:
        with zipfile.ZipFile(src) as zf:
            for member in zf.infolist():
                name = member.filename
                if not safe_zip_member(name):
                    skipped += 1
                    continue
                target = ws.joinpath(*PurePosixPath(name).parts)
                if member.is_dir() or name.endswith("/"):
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(ws, ignore_errors=True)
        fail(f"could not read zip archive: {exc}", 5)
    if skipped:
        emit(f"warning: skipped {skipped} unsafe or ignored entries in the archive")


def init_import(project: str, ws: Path, source: str) -> None:
    src = Path(source)
    if not src.is_absolute():
        candidates = [YOUR_FILES_DIR / src, Path.cwd() / src]
        src = next((c for c in candidates if c.exists()), candidates[0])
    if src.is_dir():
        ws.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, ws, ignore=shutil.ignore_patterns(".git", "node_modules"))
    elif src.is_file() and src.suffix.lower() == ".zip":
        extract_zip(src, ws)
    else:
        fail(f"source not found or not a folder/.zip: {src} "
             f"(looked in {YOUR_FILES_DIR} and the current directory)", 5)
    ensure_git_repo(ws)
    commit = run_checkpoint(ws, f"init: import {project} from {Path(source).name}")
    record_workspace(project, f"import:{source}", None)
    count = sum(1 for _ in iter_workspace_files(ws))
    emit(f"imported '{project}' from {src}\n"
         f"files: {count}\n"
         f"checkpoint {commit or '-'}: init: import {project} from {Path(source).name}")


def cmd_init(args: argparse.Namespace) -> None:
    if not valid_project(args.project):
        fail(f"invalid project name {args.project!r}: use letters, digits, '.', '_', '-'", 2)
    ws = workspace_path(args.project)
    if ws.exists():
        fail(f"workspace '{args.project}' already exists at {ws}", 2)
    chosen = [x for x in (args.template, args.repo, args.source) if x]
    if len(chosen) != 1:
        fail("init needs exactly one of --template, --repo or --source", 2)
    if args.template:
        init_template(args.project, ws, args.template)
    elif args.repo:
        init_clone(args.project, ws, args.repo)
    else:
        init_import(args.project, ws, args.source)


# ---------------------------------------------------------------- inspect

def tree_section(ws: Path) -> str:
    files = list(iter_workspace_files(ws))
    lines = [f"tree ({len(files)} files)"]
    shown = 0
    used = 0
    for path in files:
        rel = path.relative_to(ws).as_posix()
        line = f"  {rel}  {path.stat().st_size}B"
        if used + len(line) + 1 > TREE_BUDGET:
            lines.append(f"  ... ({len(files) - shown} more files)")
            break
        lines.append(line)
        used += len(line) + 1
        shown += 1
    return "\n".join(lines)


def git_section(ws: Path) -> str:
    branch = git(ws, "branch", "--show-current")
    log = git(ws, "log", "--oneline", "-6")
    if branch.returncode != 0 or log.returncode != 0:
        return "git: (not a git repository)"
    porcelain = git(ws, "status", "--porcelain")
    dirty = bool(porcelain.stdout.strip())
    lines = [f"git: branch {branch.stdout.strip() or '(detached)'} | "
             f"{'changes pending' if dirty else 'clean'}"]
    for line in log.stdout.strip().splitlines():
        lines.append(f"  {line[:100]}")
    return "\n".join(lines[: GIT_BUDGET // 20 + 2])


def source_priority(ws: Path, path: Path) -> tuple[int, str]:
    rel = path.relative_to(ws).as_posix()
    if rel == "index.html":
        return 0, rel
    if rel.lower().startswith(("readme", "package.json")):
        return 1, rel
    return 2, rel


def excerpt_section(ws: Path, budget: int) -> str:
    files = [p for p in iter_workspace_files(ws) if p.suffix.lower() in SOURCE_EXTS]
    files.sort(key=lambda p: source_priority(ws, p))
    blocks: list[str] = ["source excerpts:"]
    used = len(blocks[0]) + 1
    for path in files:
        remaining = budget - used
        if remaining < 160:
            break
        rel = path.relative_to(ws).as_posix()
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        body_lines = body.splitlines()
        excerpt = "\n".join(body_lines[:EXCERPT_LINES])[:EXCERPT_FILE_BUDGET]
        block = (f"--- {rel} (first {min(EXCERPT_LINES, len(body_lines))} "
                 f"of {len(body_lines)} lines) ---\n{excerpt}")
        if used + len(block) + 1 > budget:
            block = block[: max(0, budget - used - 22)] + "\n...[excerpt cut]"
        blocks.append(block)
        used += len(block) + 1
    if len(blocks) == 1:
        return "source excerpts: (none)"
    return "\n".join(blocks)


def cmd_inspect(args: argparse.Namespace) -> None:
    ws = require_workspace(args.project)
    header = f"workspace '{args.project}' at {ws}"
    tree = tree_section(ws)
    gits = git_section(ws)
    budget = OUTPUT_LIMIT - (len(header) + len(tree) + len(gits) + 6)
    excerpts = excerpt_section(ws, max(budget, 200))
    emit("\n\n".join([header, tree, gits, excerpts]))


# ---------------------------------------------------------------- write / undo

def gather_writes(args: argparse.Namespace) -> dict[str, str]:
    using_bundle = bool(args.bundle or args.stdin_json)
    if using_bundle and args.file:
        fail("use either --bundle/--stdin-json or --file, not both", 2)
    if args.bundle and args.stdin_json:
        fail("use either --bundle or --stdin-json, not both", 2)
    if args.stdin and args.stdin_json:
        fail("use either --stdin or --stdin-json, not both", 2)
    if args.content_file and args.stdin:
        fail("use either --content-file or --stdin, not both", 2)
    if args.content_file and not args.file:
        fail("--content-file needs --file", 2)
    if args.file and not (args.content_file or args.stdin):
        fail("--file needs --content-file or --stdin", 2)

    files: dict[str, str] = {}
    if using_bundle:
        if args.stdin_json:
            raw = sys.stdin.read()
        else:
            try:
                raw = Path(args.bundle).read_text(encoding="utf-8")
            except OSError as exc:
                fail(f"cannot read bundle file: {exc.strerror}", 2)
        try:
            mapping = json.loads(raw)
        except ValueError as exc:
            fail(f"bundle is not valid JSON: {exc}", 2)
        if not isinstance(mapping, dict):
            fail("bundle JSON must map file paths to contents", 2)
        for rel, content in mapping.items():
            if not isinstance(content, str):
                fail(f"bundle value for {rel!r} must be a string", 2)
            files[rel] = content
    if args.file:
        if args.content_file:
            try:
                content = Path(args.content_file).read_text(encoding="utf-8")
            except OSError as exc:
                fail(f"cannot read content file: {exc.strerror}", 2)
        else:
            content = sys.stdin.read()
        files[args.file] = content
    if not files:
        fail("nothing to write: pass --bundle/--stdin-json, or --file with "
             "--content-file/--stdin", 2)
    for rel in files:
        if not safe_relpath(rel):
            fail(f"unsafe file path {rel!r}: use a relative path inside the project", 2)
    return files


def cmd_write(args: argparse.Namespace) -> None:
    ws = require_workspace(args.project)
    files = gather_writes(args)
    for rel, content in files.items():
        target = ws.joinpath(*PurePosixPath(rel).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    commit = run_checkpoint(ws, args.message)
    if commit is None:
        emit(f"written {len(files)} file(s); nothing changed in '{args.project}' "
             f"(content identical)")
        return
    changed = changed_files(ws)
    changed_indented = "\n".join(f"  {line}" for line in changed.splitlines()) \
        if changed else "  (no file summary)"
    emit(f"written {len(files)} file(s) to '{args.project}'\n"
         f"checkpoint {commit}: {args.message}\n"
         f"{changed_indented}")


def cmd_undo(args: argparse.Namespace) -> None:
    ws = require_workspace(args.project)
    head = git(ws, "rev-parse", "--short", "HEAD").stdout.strip()
    if git(ws, "rev-parse", "--verify", "--quiet", "HEAD~1").returncode != 0:
        fail("nothing to undo: no earlier commit in the history", 4)
    r = git(ws, "reset", "--hard", "HEAD~1")
    if r.returncode != 0:
        fail(f"git reset failed: {r.stderr.strip()}", 4)
    restored = git(ws, "log", "-1", "--oneline").stdout.strip()
    emit(f"undid checkpoint {head}\nnow at: {restored}")


# ---------------------------------------------------------------- export / pr

def cmd_export(args: argparse.Namespace) -> None:
    ws = require_workspace(args.project)
    dest_dir = Path(YOUR_FILES_DIR)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        fail(f"cannot create export directory {dest_dir}: {exc.strerror}", 9)
    dest = dest_dir / f"{args.project}.zip"
    count = 0
    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in iter_workspace_files(ws):
                zf.write(path, path.relative_to(ws).as_posix())
                count += 1
    except OSError as exc:
        fail(f"zip export failed: {exc.strerror}", 9)
    size_kb = dest.stat().st_size / 1024
    emit(f"exported '{args.project}' to {dest} ({count} files, {size_kb:.1f} KB)")


def parse_remote(url: str) -> tuple[str, str] | None:
    m = re.match(r"^https://[^/]*github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    if not m:
        m = re.match(r"^git@[^/]*github\.com:([^/]+)/([^/]+?)(?:\.git)?/?$", url)
    return (m.group(1), m.group(2)) if m else None


def push_branch(ws: Path, token: str, branch: str) -> None:
    token = token.strip()
    if not token or "\n" in token or " " in token:
        fail("GITHUB_TOKEN looks invalid (empty or contains whitespace)", 7)
    with tempfile.TemporaryDirectory(prefix="pocket-dev-") as tmp:
        helper = Path(tmp) / "cubbie-credential-helper.sh"
        helper.write_text("#!/bin/sh\n"
                          "echo username=x-access-token\n"
                          f"echo password={token}\n", encoding="utf-8")
        helper.chmod(0o700)
        r = git(ws, "-c", "credential.helper=", "-c", f"credential.helper={helper}",
                "push", "origin", branch)
    if r.returncode != 0:
        fail(f"git push failed:\n{tail(r.stderr, 3)}", 8)


def create_pull_request(token: str, owner: str, repo: str, branch: str,
                        title: str, body: str) -> str:
    import requests
    api = f"https://api.github.com/repos/{owner}/{repo}"
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    try:
        info = requests.get(api, headers=headers, timeout=15)
        base = info.json().get("default_branch") if info.ok else None
        payload = {"title": title, "head": branch, "base": base or "main",
                   "body": body or "Created by cubbie coding harness from Cubbie."}
        resp = requests.post(f"{api}/pulls", headers=headers, json=payload, timeout=15)
    except requests.RequestException as exc:
        fail(f"GitHub API request failed ({type(exc).__name__}).", 8)
    if resp.status_code == 201:
        return resp.json().get("html_url", "(no url returned)")
    try:
        detail = resp.json().get("message", "")
    except ValueError:
        detail = ""
    fail(f"pull request failed (HTTP {resp.status_code}): {detail}", 8)


def cmd_pr(args: argparse.Namespace) -> None:
    ws = require_workspace(args.project)
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        fail("GITHUB_TOKEN is not set. Ask the student to save a GitHub token "
             "(repo scope) first.", 7)
    origin = git(ws, "remote", "get-url", "origin")
    if origin.returncode != 0 or not origin.stdout.strip():
        fail("workspace has no GitHub remote; init it from a GitHub URL or add "
             "an origin remote", 8)
    parsed = parse_remote(origin.stdout.strip())
    if not parsed:
        fail(f"cannot parse GitHub owner/repo from remote {origin.stdout.strip()!r}", 8)
    owner, repo = parsed
    branch = f"cubbie/pr-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    r = git(ws, "checkout", "-b", branch)
    if r.returncode != 0:
        fail(f"git branch failed: {r.stderr.strip() or r.stdout.strip()}", 4)
    push_branch(ws, token, branch)
    pr_url = create_pull_request(token, owner, repo, branch, args.title, args.message)
    emit(f"pushed branch {branch} to {owner}/{repo}\npull request: {pr_url}")


# ---------------------------------------------------------------- sample

def sample() -> int:
    try:
        data = json.loads(SAMPLE.read_text(encoding="utf-8"))["workspace"]
    except (OSError, ValueError, KeyError):
        fail("sample data missing or invalid (assets/sample_data.json)", 2)
    git_info = data.get("git", {})
    lines = [f"cubbie coding harness workspace (sample) - {data.get('project')}",
             f"root: {data.get('root')}",
             f"template: {data.get('template')}",
             f"tree ({len(data.get('tree', []))} files):"]
    for entry in data.get("tree", []):
        lines.append(f"  {entry.get('path')}  {entry.get('bytes')}B")
    lines.append(f"git: branch {git_info.get('branch')} | "
                 f"{'changes pending' if not git_info.get('clean') else 'clean'}")
    lines.append("checkpoints (latest first):")
    for cp in git_info.get("checkpoints", []):
        lines.append(f"  {cp.get('hash')}  {cp.get('message')}  "
                     f"({cp.get('changed')} file(s) changed)")
    for ex in data.get("excerpts", []):
        lines.append(f"excerpt {ex.get('path')} (lines {ex.get('lines')}):")
        for ln in ex.get("content", "").splitlines():
            lines.append(f"  {ln}")
    lines.append("(sample mode: printed from bundled assets, no state written)")
    emit("\n".join(lines))
    return 0


# ---------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="cubbie coding harness workspace engine: project scaffolding, "
                    "git checkpoints, zip export and GitHub PRs")
    parser.add_argument("--sample", action="store_true",
                        help="offline demo from assets/sample_data.json; "
                             "no state writes, no network")
    sub = parser.add_subparsers(dest="command", metavar="command")

    p = sub.add_parser("init", help="create a workspace from a template, "
                                    "GitHub URL, or folder/zip")
    p.add_argument("--project", required=True, help="workspace/project name")
    p.add_argument("--template", choices=list(TEMPLATES),
                   help="bundled starter template")
    p.add_argument("--repo", help="https:// GitHub repository URL")
    p.add_argument("--source", help="folder or .zip in /workspace/your_files/")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("inspect", help="bounded workspace summary")
    p.add_argument("--project", required=True)
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("write", help="write file(s) and create a git checkpoint")
    p.add_argument("--project", required=True)
    p.add_argument("--file", help="relative file path to write")
    p.add_argument("--content-file", help="file whose contents become --file's content")
    p.add_argument("--stdin", action="store_true", help="read content from stdin")
    p.add_argument("--bundle", help="JSON file mapping relative paths to contents")
    p.add_argument("--stdin-json", action="store_true",
                   help="read a JSON bundle from stdin")
    p.add_argument("--message", default="checkpoint: update files",
                   help="checkpoint commit message")
    p.set_defaults(func=cmd_write)

    p = sub.add_parser("undo", help="roll back to the previous git checkpoint")
    p.add_argument("--project", required=True)
    p.set_defaults(func=cmd_undo)

    p = sub.add_parser("export", help="export a clean .zip to /workspace/your_files/")
    p.add_argument("--project", required=True)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("pr", help="push a branch and open a GitHub pull request "
                                  "(needs GITHUB_TOKEN)")
    p.add_argument("--project", required=True)
    p.add_argument("--title", required=True, help="pull request title")
    p.add_argument("--message", default="", help="pull request body text")
    p.set_defaults(func=cmd_pr)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.sample:
        return sample()
    func = getattr(args, "func", None)
    if func is None:
        emit("no command given: use init, inspect, write, undo, export, pr, "
             "or --sample")
        return 2
    func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
