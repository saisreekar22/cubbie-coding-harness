#!/usr/bin/env python3
"""cubbie coding harness build/test runner: verifies student workspaces.

Auto-detects the workspace stack (static HTML/JS/CSS web app, Node/Vite/React
web app, or Python project), runs the matching syntax checks, builds, and
test suites, and prints a compact stage-by-stage report. Every failure exits
with code 4 and shows the failing stage, its command, and a condensed error
tail so Cubbie can fix the file and re-run. All stdout stays under 7,500
characters so Cubbie never loses context or exit statuses.

Exit codes:
  0  all checks passed
  2  bad arguments (missing flags, invalid project)
  3  project not found
  4  verification failure (syntax check, build, or tests)
  5  unsupported project type (nothing detected)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

OUTPUT_LIMIT = 7400
STAGE_DETAIL = 400
ERR_TAIL_LINES = 8
IGNORED_DIRS = {".git", "node_modules", "dist", "build", "__pycache__",
                ".pytest_cache", ".mypy_cache", ".cache", ".venv", "venv"}
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
EXTERNAL_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.I)
SKILL_ROOT = Path(__file__).resolve().parent.parent


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


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def tail(text: str, lines: int = ERR_TAIL_LINES) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def detail(text: str) -> str:
    text = ANSI_RE.sub("", text).strip()
    return text if len(text) <= STAGE_DETAIL else text[: STAGE_DETAIL - 3] + "..."


def iter_files(ws: Path, suffix: str):
    for root, dirs, files in os.walk(ws):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        for name in sorted(files):
            if name.endswith(suffix):
                yield Path(root) / name


# ---------------------------------------------------------------- detection

def detect_type(ws: Path) -> str | None:
    if (ws / "package.json").is_file():
        return "node"
    if (ws / "index.html").is_file():
        return "static-web"
    if any(iter_files(ws, ".py")) or any(
            (ws / n).is_file() for n in
            ("requirements.txt", "pyproject.toml", "setup.py")):
        return "python"
    return None


# ---------------------------------------------------------------- static web

class AssetLinkParser(HTMLParser):
    """Collects local <script src> and <link href> targets."""

    def __init__(self, base: Path):
        super().__init__()
        self.base = base
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: dict) -> None:
        attr = "src" if tag == "script" else "href" if tag == "link" else None
        if attr is None:
            return
        value = dict(attrs).get(attr, "").strip()
        if not value or EXTERNAL_RE.match(value):
            return
        path = unquote(urlsplit(value).path)
        if not path:
            return
        target = self.base / path.lstrip("/")
        self.links.append((tag, target))


def check_static_web(ws: Path) -> list[dict]:
    stages = []

    index = ws / "index.html"
    html = index.read_text(encoding="utf-8", errors="replace")
    ok = bool(html.strip())
    stages.append({"name": "html",
                   "command": "verify index.html exists and is non-empty",
                   "ok": ok,
                   "detail": f"{len(html)} chars" if ok else "index.html is empty"})
    if not ok:
        return stages

    parser = AssetLinkParser(ws)
    parser.feed(html)
    missing = [f"{tag} -> {t.relative_to(ws)}"
               for tag, t in parser.links if not t.is_file()]
    stages.append({"name": "asset-links",
                   "command": "validate local <script src>/<link href> targets",
                   "ok": not missing,
                   "detail": f"{len(parser.links)} link(s)"
                   if not missing else "missing: " + ", ".join(missing)})

    js_files = list(iter_files(ws, ".js"))
    bad = []
    errors = []
    for js in js_files:
        r = run(["node", "--check", str(js)], ws)
        if r.returncode != 0:
            bad.append(js)
            errors.append(f"node --check {js.relative_to(ws)}:\n"
                          f"{detail(r.stderr.strip())}")
    stages.append({"name": "js-syntax",
                   "command": "node --check every local .js file",
                   "ok": not bad,
                   "detail": f"{len(js_files)} file(s)"
                   if not bad else "\n".join(errors)})

    test_scripts = sorted(p for p in iter_files(ws, ".test.js")
                          if p.parent.name == "tests")
    fails = []
    outs = []
    for script in test_scripts:
        r = run(["node", str(script)], ws)
        if r.returncode != 0:
            fails.append(script)
            outs.append(f"node {script.relative_to(ws)}:\n"
                        f"{detail((r.stderr or r.stdout).strip())}")
    stages.append({"name": "tests",
                   "command": (f"node {test_scripts[0].relative_to(ws)}"
                               if len(test_scripts) == 1 else
                               f"node x{len(test_scripts)} test scripts")
                   if test_scripts else "no test scripts in tests/",
                   "ok": not fails,
                   "detail": (f"{len(test_scripts)} script(s) passed"
                              if test_scripts and not fails else
                              "none present" if not test_scripts else
                              "\n".join(outs))})
    return stages


# ---------------------------------------------------------------- node

def check_node(ws: Path) -> list[dict]:
    stages = []
    try:
        pkg = json.loads((ws / "package.json").read_text(encoding="utf-8"))
        scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
    except (OSError, ValueError) as exc:
        fail(f"cannot read package.json: {exc}", 4)
    stages.append({"name": "manifest", "command": "parse package.json",
                   "ok": True, "detail": f"{len(scripts)} script(s)"})

    if not (ws / "node_modules").is_dir():
        r = run(["npm", "install", "--no-audit", "--no-fund"], ws)
        stages.append({"name": "install",
                       "command": "npm install",
                       "ok": r.returncode == 0,
                       "detail": "dependencies installed"
                       if r.returncode == 0 else
                       f"npm install failed:\n{detail(tail(r.stderr or r.stdout))}"})
        if r.returncode != 0:
            return stages

    if "build" in scripts:
        r = run(["npm", "run", "build"], ws)
        stages.append({"name": "build", "command": "npm run build",
                       "ok": r.returncode == 0,
                       "detail": "build ok"
                       if r.returncode == 0 else
                       f"build failed:\n{detail(tail(r.stderr or r.stdout))}"})
        if r.returncode != 0:
            return stages

    if "test" in scripts:
        r = run(["npm", "test"], ws)
        stages.append({"name": "tests", "command": "npm test",
                       "ok": r.returncode == 0,
                       "detail": "tests passed"
                       if r.returncode == 0 else
                       f"tests failed:\n{detail(tail(r.stderr or r.stdout))}"})
        if r.returncode != 0:
            return stages
    else:
        stages.append({"name": "tests", "command": "no test script configured",
                       "ok": True, "detail": "skipped"})
    return stages


# ---------------------------------------------------------------- python

def check_python(ws: Path) -> list[dict]:
    stages = []
    py_files = list(iter_files(ws, ".py"))
    bad = []
    errors = []
    for py in py_files:
        r = run([sys.executable, "-m", "py_compile", str(py)], ws)
        if r.returncode != 0:
            bad.append(py)
            errors.append(f"py_compile {py.relative_to(ws)}:\n"
                          f"{detail(tail(r.stderr or r.stdout))}")
    stages.append({"name": "syntax", "command": "python3 -m py_compile every .py file",
                   "ok": not bad,
                   "detail": f"{len(py_files)} file(s)"
                   if not bad else "\n".join(errors)})
    if bad:
        return stages

    test_files = [p for p in py_files
                  if p.name.startswith("test_") or p.name.endswith("_test.py")]
    if test_files:
        r = run([sys.executable, "-m", "pytest", "-q"], ws)
        stages.append({"name": "tests", "command": "python3 -m pytest -q",
                       "ok": r.returncode == 0,
                       "detail": "tests passed"
                       if r.returncode == 0 else
                       f"tests failed:\n{detail(tail(r.stdout or r.stderr))}"})
    else:
        stages.append({"name": "tests", "command": "no test files detected",
                       "ok": True, "detail": "skipped"})
    return stages


# ---------------------------------------------------------------- report

CHECKERS = {"static-web": check_static_web, "node": check_node,
            "python": check_python}


def render_report(project: str, ptype: str, stages: list[dict],
                   ws: Path | None = None) -> tuple[str, bool]:
    where = f" at {ws}" if ws else ""
    lines = [f"project '{project}' ({ptype}){where}"]
    for stage in stages:
        if stage["ok"]:
            lines.append(f"stage {stage['name']}: pass - {stage['command']}"
                         f" ({stage['detail']})")
        else:
            lines.append(f"stage {stage['name']}: FAIL - {stage['command']}")
            if stage["detail"]:
                for ln in str(stage["detail"]).splitlines():
                    lines.append(f"  {ln}")
    passed = sum(1 for s in stages if s["ok"])
    ok = passed == len(stages)
    if ok:
        lines.append(f"summary: {passed}/{len(stages)} stages passed; exit 0")
    else:
        failed = [s["name"] for s in stages if not s["ok"]]
        lines.append(f"summary: {passed}/{len(stages)} stages passed; "
                     f"failing stage(s): {', '.join(failed)}; exit 4")
    return "\n".join(lines), ok


def cmd_check(args: argparse.Namespace) -> None:
    if not NAME_RE.match(args.project or ""):
        fail(f"invalid project name {args.project!r}: use letters, digits, "
             f"'.', '_', '-'", 2)
    ws = data_root() / "workspaces" / args.project
    if not ws.is_dir():
        fail(f"no workspace named '{args.project}' (init it first)", 3)
    ptype = detect_type(ws)
    if ptype is None:
        fail(f"cannot verify '{args.project}': no package.json, index.html, "
             f"or .py files to detect a project type", 5)
    stages = CHECKERS[ptype](ws)
    report, ok = render_report(args.project, ptype, stages, ws)
    emit(report)
    if not ok:
        sys.exit(4)


# ---------------------------------------------------------------- sample

def sample() -> int:
    tpl = SKILL_ROOT / "assets" / "templates" / "modern-web"
    stages = check_static_web(tpl)
    report, ok = render_report("sample-modern-web", "static-web", stages)
    report += ("\n(sample mode: verified the bundled assets/templates/ "
               "modern-web starter; no state written, no network)")
    emit(report)
    return 0 if ok else 4


# ---------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="cubbie coding harness build/test runner: syntax, build and "
                    "test verification with compact diagnostics")
    parser.add_argument("--sample", action="store_true",
                        help="offline demo checking the bundled template; "
                             "no state writes, no network")
    sub = parser.add_subparsers(dest="command", metavar="command")
    p = sub.add_parser("check", help="verify a workspace")
    p.add_argument("--project", required=True, help="workspace/project name")
    p.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.sample:
        return sample()
    func = getattr(args, "func", None)
    if func is None:
        emit("no command given: use check --project <name>, or --sample")
        return 2
    func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
