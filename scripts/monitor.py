#!/usr/bin/env python3
"""cubbie coding harness CI monitor: GitHub Actions status transition alerts.

`check --repo <owner/repo or github url>` polls the GitHub Actions API
(api.github.com) for a repository's latest completed workflow run - zero auth
for public repos, GITHUB_TOKEN when provided - compares the conclusion with
the last recorded status in persistent state, and signals transitions:
exit 2 with a formatted alert (workflow, branch, commit, run URL) when CI
flips between passing and failing, exit 0 with a short no_change summary
otherwise. `--sample` replays a bundled fixture with no network and no state
writes. All stdout stays under 7,500 characters so Cubbie never loses
context or exit statuses.

Exit codes:
  0  no change (or initial check recorded / sample mode)
  2  CI state transition detected (alert printed)
  3  repository not found or no access (bad repo, private repo, bad token)
  4  GitHub API request failed (network or HTTP error)
  5  invalid arguments
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_LIMIT = 7400
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
API_BASE = "https://api.github.com/repos"
REPO_SLUG_RE = re.compile(
    r"^(?:https?://(?:www\.)?github\.com/)?([A-Za-z0-9_.-]+)/"
    r"([A-Za-z0-9_.-]+?)(?:\.git)?/?$", re.I)
FAIL_CONCLUSIONS = {"failure", "startup_failure", "timed_out", "cancelled"}
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


def parse_repo(arg: str) -> tuple[str, str]:
    m = REPO_SLUG_RE.match(arg.strip())
    if not m:
        fail(f"cannot parse a GitHub repo from {arg!r}: use owner/repo or a "
             f"github.com URL", 5)
    return m.group(1), m.group(2)


def classify(conclusion: str | None) -> str:
    return "success" if conclusion == "success" else "failure"


# ---------------------------------------------------------------- check

def fetch_latest_run(owner: str, repo: str) -> dict | None:
    """GET /actions/runs and return the latest completed, judged run."""
    import requests
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{API_BASE}/{owner}/{repo}/actions/runs?per_page=15"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
    except requests.RequestException as exc:
        fail(f"GitHub API request failed ({type(exc).__name__}).", 4)
    if resp.status_code == 404:
        fail(f"repo {owner}/{repo} not found (or private and GITHUB_TOKEN "
             f"is not set)", 3)
    if resp.status_code in (401, 403):
        fail(f"no access to {owner}/{repo} (HTTP {resp.status_code}): bad or "
             f"missing GITHUB_TOKEN, or rate-limited", 3)
    if resp.status_code != 200:
        fail(f"GitHub API error (HTTP {resp.status_code}).", 4)
    try:
        runs = resp.json().get("workflow_runs", [])
    except ValueError:
        fail("GitHub API returned invalid JSON.", 4)
    for run in runs:
        if run.get("status") == "completed" and run.get("conclusion"):
            return run
    return None


def record(repo_slug: str, run: dict) -> None:
    state = load_state()
    state.setdefault("monitors", {})[repo_slug] = {
        "last_conclusion": run.get("conclusion"),
        "last_run_id": run.get("id"),
        "last_check": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_state(state)


def alert(run: dict, repo_slug: str, prev: str, new: str) -> None:
    verb = "RECOVERED" if new == "success" else "ALERT"
    sha = str(run.get("head_sha") or "")[:12]
    emit(f"CI {verb}: {prev or '(first check)'} -> {new}\n"
         f"repo: {repo_slug}\n"
         f"workflow: {run.get('name')}\n"
         f"branch: {run.get('head_branch')}\n"
         f"commit: {sha}\n"
         f"conclusion: {run.get('conclusion')}\n"
         f"run: {run.get('html_url')}\n"
         f"state saved; the next check-in reports no_change unless it flips")


def no_change(run: dict, repo_slug: str, prev: str) -> None:
    emit(f"no_change\n"
         f"repo: {repo_slug}\n"
         f"latest run: {run.get('conclusion')} "
         f"(id {run.get('id')}, {run.get('html_url')})\n"
         f"last recorded: {prev or '(none)'}")


def cmd_check(args: argparse.Namespace) -> None:
    owner, repo = parse_repo(args.repo)
    repo_slug = f"{owner}/{repo}"
    run = fetch_latest_run(owner, repo)
    if run is None:
        emit(f"no_change\nrepo: {repo_slug}\n"
             f"no completed workflow runs yet; nothing recorded")
        return
    prev_state = load_state().get("monitors", {}).get(repo_slug, {})
    prev = prev_state.get("last_conclusion") or ""
    prev_class = classify(prev) if prev else None
    new = run.get("conclusion")
    new_class = classify(new)
    if prev_class is None:
        record(repo_slug, run)
        if new_class == "failure":
            alert(run, repo_slug, "", new)
            sys.exit(2)
        no_change(run, repo_slug, prev)
        return
    if new_class != prev_class:
        record(repo_slug, run)
        alert(run, repo_slug, prev, new)
        sys.exit(2)
    if prev != new:
        record(repo_slug, run)
    no_change(run, repo_slug, prev)


# ---------------------------------------------------------------- sample

def sample() -> int:
    try:
        data = json.loads(SAMPLE.read_text(encoding="utf-8"))["monitor"]
    except (OSError, ValueError, KeyError):
        fail("sample data missing or invalid (assets/sample_data.json)", 2)
    runs = data.get("runs", {}).get("workflow_runs", [])
    latest = next((r for r in runs
                   if r.get("status") == "completed" and r.get("conclusion")),
                  None)
    if latest is None:
        fail("sample fixture has no completed run", 2)
    prev = data.get("previous_state", {}).get("last_conclusion", "")
    prev_class = classify(prev) if prev else None
    if prev_class is not None and prev_class != classify(latest["conclusion"]):
        alert(latest, data.get("repo", "sample/repo"), prev,
              latest["conclusion"])
    else:
        no_change(latest, data.get("repo", "sample/repo"), prev)
    emit("(sample mode: replayed the bundled CI fixture, no network, "
         "no state written)")
    return 0


# ---------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="cubbie coding harness CI monitor: GitHub Actions run status "
                    "and pass/fail transition alerts")
    parser.add_argument("--sample", action="store_true",
                        help="offline demo from assets/sample_data.json; "
                             "no state writes, no network")
    sub = parser.add_subparsers(dest="command", metavar="command")
    p = sub.add_parser("check", help="poll a repo's latest CI run")
    p.add_argument("--repo", required=True,
                   help="owner/repo or https://github.com/owner/repo URL")
    p.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.sample:
        return sample()
    func = getattr(args, "func", None)
    if func is None:
        emit("no command given: use check --repo <owner/repo>, or --sample")
        return 5
    func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
