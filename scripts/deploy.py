#!/usr/bin/env python3
"""cubbie coding harness web deployment: publish student sites to Netlify.

`status` reports whether the Netlify CLI session is signed in (exit 3 when
sign-in is required so Cubbie can start the non-blocking browser login from
cubbie.yaml). `deploy` auto-detects the publishable directory (dist/, build/,
or the workspace root with index.html, building Node projects first when
needed), creates or updates a Netlify site, and saves the site_id in
persistent state so later deployments update the same live URL. `--sample`
prints a bundled demo result with no network access. All stdout stays under
7,500 characters so Cubbie never loses context or exit statuses.

Exit codes:
  0  ok (signed in / deployed; live URL printed)
  2  bad arguments, unknown project, or nothing publishable found
  3  Netlify sign-in required (CLI missing or not authenticated)
  4  Netlify command failed (site name taken, deploy error, ...)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_LIMIT = 7400
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SITE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
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
    return Path(os.environ.get("SKILL_DATA_DIR")
                or Path.home() / ".config" / "cubbie-coding-harness")


def workspace_path(project: str) -> Path:
    return data_root() / "workspaces" / project


def load_state() -> dict:
    try:
        return json.loads((data_root() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "state.json").write_text(json.dumps(state, indent=2),
                                     encoding="utf-8")


def netlify(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run the Netlify CLI; FileNotFoundError is treated as not signed in."""
    try:
        return subprocess.run(["netlify", *args], cwd=str(cwd) if cwd else None,
                             capture_output=True, text=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(
            args=["netlify", *args], returncode=127, stdout="",
            stderr="netlify CLI not found on PATH")


def parse_cli_json(text: str) -> dict:
    """Parse a Netlify CLI --json payload, tolerating stray log lines."""
    text = ANSI_RE.sub("", text).strip()
    try:
        return json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except ValueError:
                pass
    return {}


def tail(text: str, lines: int = 4) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


# ---------------------------------------------------------------- status

def netlify_account(payload: dict) -> str:
    for source in (payload.get("account"), payload.get("user"), payload):
        if isinstance(source, dict):
            email = source.get("email") or source.get("id")
            if email:
                return str(email)
    return "your Netlify account"


def cmd_status(args: argparse.Namespace) -> None:
    r = netlify("status", "--json")
    if r.returncode != 0:
        fail("not signed in to Netlify (or the CLI is not installed). "
             "Ask the student to complete the Netlify login link first.", 3)
    account = netlify_account(parse_cli_json(r.stdout or r.stderr))
    emit(f"signed in to Netlify as {account}\n"
         "ready to deploy: deploy.py deploy --project <name> --name <site-name>")


# ---------------------------------------------------------------- deploy

def detect_publish_dir(ws: Path) -> Path | None:
    for dirname in ("dist", "build"):
        candidate = ws / dirname
        if candidate.is_dir() and any(candidate.iterdir()):
            return candidate
    if (ws / "index.html").is_file():
        return ws
    return None


def try_build(ws: Path) -> bool:
    """Build a Node project so dist/ or build/ appears. Returns True if built."""
    pkg_path = ws / "package.json"
    if not pkg_path.is_file():
        return False
    try:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        if "build" not in (pkg.get("scripts") or {}):
            return False
    except (OSError, ValueError):
        return False
    if not (ws / "node_modules").is_dir():
        install = subprocess.run(["npm", "install", "--no-audit", "--no-fund"],
                                 cwd=str(ws), capture_output=True, text=True)
        if install.returncode != 0:
            fail("npm install failed:\n" + tail(install.stderr or install.stdout),
                 4)
    build = subprocess.run(["npm", "run", "build"], cwd=str(ws),
                           capture_output=True, text=True)
    if build.returncode != 0:
        fail("production build failed (fix with runner.py check, then retry):\n"
             + tail(build.stderr or build.stdout), 4)
    return True


def count_files(pub: Path) -> int:
    if pub.is_file():
        return 1
    return sum(1 for f in pub.rglob("*") if f.is_file())


def create_site(site_name: str) -> tuple[str, str]:
    r = netlify("sites:create", "--name", site_name, "--json")
    if r.returncode != 0:
        fail(f"could not create Netlify site {site_name!r} (name may be taken; "
             f"try another --name):\n{tail(r.stderr or r.stdout)}", 4)
    payload = parse_cli_json(r.stdout or r.stderr)
    site = payload.get("site") if isinstance(payload.get("site"), dict) else {}
    site_id = (payload.get("site_id") or payload.get("id")
               or site.get("site_id") or site.get("id"))
    url = (payload.get("ssl_url") or payload.get("url")
           or site.get("ssl_url") or site.get("url"))
    if not site_id:
        fail(f"could not read the new site_id from the Netlify CLI response:\n"
             f"{tail(r.stdout or r.stderr)}", 4)
    return str(site_id), str(url or f"https://{site_name}.netlify.app")


def cmd_deploy(args: argparse.Namespace) -> None:
    if not NAME_RE.match(args.project or ""):
        fail(f"invalid project name {args.project!r}: use letters, digits, "
             f"'.', '_', '-'", 2)
    if not SITE_NAME_RE.match(args.name or ""):
        fail(f"invalid site name {args.name!r}: use lowercase letters, digits "
             f"and single dashes (a netlify.app subdomain)", 2)
    ws = workspace_path(args.project)
    if not ws.is_dir():
        fail(f"no workspace named '{args.project}' (init it first)", 2)
    status = netlify("status", "--json")
    if status.returncode != 0:
        fail("not signed in to Netlify (or the CLI is not installed). "
             "Ask the student to complete the Netlify login link first.", 3)
    pub = detect_publish_dir(ws)
    if pub is None:
        try_build(ws)
        pub = detect_publish_dir(ws)
    if pub is None:
        fail(f"nothing publishable in '{args.project}': no dist/, build/, or "
             f"root index.html (run runner.py check first)", 2)

    state = load_state()
    sites = state.setdefault("sites", {})
    saved = sites.get(args.name, {})
    if saved.get("site_id"):
        site_id, url = saved["site_id"], saved.get("url", "")
        r = netlify("deploy", "--site", site_id, "--prod",
                    "--dir", str(pub), cwd=ws)
    else:
        site_id, url = create_site(args.name)
        r = netlify("deploy", "--site", site_id, "--prod",
                    "--dir", str(pub), cwd=ws)
    if r.returncode != 0:
        fail(f"netlify deploy failed:\n{tail(r.stderr or r.stdout)}", 4)
    payload = parse_cli_json(r.stdout or r.stderr)
    if not url:
        url = payload.get("deploy_url") or payload.get("url") or "(unknown url)"

    sites[args.name] = {
        "site_id": site_id,
        "url": url,
        "project": args.project,
        "publish_dir": str(pub.relative_to(ws) if pub != ws else "."),
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_state(state)
    emit(f"deployed '{args.project}' to {url}\n"
         f"site: {args.name} ({site_id})\n"
         f"published {count_files(pub)} file(s) from "
         f"{'.' if pub == ws else pub.relative_to(ws)}\n"
         f"later deploys with --name {args.name} update this same URL")


# ---------------------------------------------------------------- sample

def sample() -> int:
    try:
        data = json.loads(SAMPLE.read_text(encoding="utf-8"))["deploy"]
    except (OSError, ValueError, KeyError):
        fail("sample data missing or invalid (assets/sample_data.json)", 2)
    emit(f"deploy (sample)\n"
         f"project: {data.get('project')}\n"
         f"site: {data.get('site_name')} ({data.get('site_id')})\n"
         f"published {data.get('files_published')} file(s) from "
         f"{data.get('publish_dir')} in {data.get('deploy_time_seconds')}s\n"
         f"live URL: {data.get('url')}\n"
         f"account: {data.get('account')}\n"
         f"(sample mode: printed from bundled assets, no network, "
         f"no state written)")
    return 0


# ---------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="cubbie coding harness web deployment: Netlify status, "
                    "production deploys and persistent site IDs")
    parser.add_argument("--sample", action="store_true",
                        help="offline demo from assets/sample_data.json; "
                             "no state writes, no network")
    sub = parser.add_subparsers(dest="command", metavar="command")

    p = sub.add_parser("status", help="check Netlify sign-in")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("deploy", help="deploy a workspace to a live URL")
    p.add_argument("--project", required=True, help="workspace/project name")
    p.add_argument("--name", required=True,
                   help="netlify.app site name (reused across deploys)")
    p.set_defaults(func=cmd_deploy)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.sample:
        return sample()
    func = getattr(args, "func", None)
    if func is None:
        emit("no command given: use status, deploy --project <name> "
             "--name <site-name>, or --sample")
        return 2
    func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
