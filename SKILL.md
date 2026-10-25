---
name: cubbie-coding-harness
description: >-
  Builds, tests, fixes, deploys, and ships real software projects entirely
  over text. Use when the student wants to build a web app, create or
  scaffold a project, write or modify code, fix a bug, run tests or
  checks, deploy a website live, export code as a zip, push a branch or
  open a pull request on GitHub, or watch a repo's CI and get alerts.
  Triggers include "build me", "make me a website", "fix this bug",
  "run my tests", "deploy my site", "export my code", "open a PR", and
  "watch my CI".
---

# cubbie coding harness

You are the coding brain; the scripts in this folder are your deterministic
hands. You write and edit the student's code yourself, then hand files to
the scripts, which store projects safely, checkpoint every change in local
git, run checks and builds, deploy to a live URL, and watch CI. Nothing
here calls another AI - no extra API keys to buy before the first build.

## When to use

Any message about creating, changing, checking, shipping, or exporting
code: "build me a portfolio site", "fix the login bug in my repo",
"run my tests", "deploy it", "send me the code", "undo that last change",
"watch my repo's CI and tell me if it breaks".

## How it works

- Projects persist in the student's private sandbox between conversations,
  under the skill's data directory; nothing is lost when the chat ends.
- Files the student sends in the chat arrive in `/workspace/your_files/`.
- Every write creates a local git checkpoint, so any change can be undone
  even with no accounts connected.
- Zero setup by default: bundled web templates, public GitHub clones, zip
  import/export, and public CI checks need no sign-in at all.
- Only two things ever need the student: a Netlify login link for live
  deploys, and a saved GitHub token for pushing branches or opening pull
  requests. Both are optional until the moment they matter.
- Each script prints short, bounded output (under 7,500 characters) so
  nothing important gets cut off - read it fully before acting.

## Setup (only when needed)

- Netlify, for live deploys: run `python3 scripts/deploy.py status`.
  Exit 0 means signed in. Exit 3 means the student must sign in: start the
  Netlify login (declared in cubbie.yaml, it prints a link and exits -
  it never waits), send the link, and ask the student to tap it and
  approve. Then re-run the status command.
- GitHub, for pushes and pull requests only: ask the student to create a
  personal access token with the `repo` scope at
  https://github.com/settings/tokens and save it with your secure input
  page, so the value never appears in the chat. Cloning public repos and
  watching public CI never need the token.

## Workflow: Build from scratch

1. Ask up to three quick questions: what to build, plain HTML/JS or React,
   and any name they want for the site. Otherwise pick sensible defaults.
2. Scaffold: `python3 scripts/workspace.py init --project <name>
   --template modern-web` (zero-install static web) or
   `--template react-spa` (Vite + React).
3. Author the code yourself, then write each file (or a JSON bundle of
   files) with `python3 scripts/workspace.py write --project <name>
   --file <relpath> --content-file <source> --message "<what changed>"`.
   Every write lands as a local git checkpoint.
4. Verify: `python3 scripts/runner.py check --project <name>`. If it
   fails, read the failing stage and error tail, fix the file, write it
   again, and re-run. Repeat up to three times before reporting a block.
5. Show the result, then continue to Deploy or Export below with the
   student's yes.

If a build or install will take a while, run it as a background task and
report back when it finishes. Remember the student's preferred framework,
site names, and deploy choices with your memory so next time needs no
questions. If the project is for a class, pull the requirements from the
course's Canvas site first.

## Workflow: Fix a bug or add a feature in a GitHub repo

1. Clone: `python3 scripts/workspace.py init --project <name> --repo
   <https-github-url>` - public repos need no token.
2. Reproduce: `python3 scripts/runner.py check --project <name>` and
   `python3 scripts/workspace.py inspect --project <name>` for a bounded
   view of the tree, checkpoints, and file excerpts.
3. Fix the code yourself and write changes via `workspace.py write`.
4. Re-run the check until it passes.
5. Ask the student's yes before pushing anything to GitHub. Then run
   `python3 scripts/workspace.py pr --project <name> --title "<title>"`
   (uses the saved GitHub token). Report the pull request URL it prints.

## Workflow: Deploy or export

- Import work the student sends: `python3 scripts/workspace.py init
  --project <name> --source <folder-or-zip>` reads from
  `/workspace/your_files/` and commits an initial checkpoint.
- Deploy live: get the student's yes first - publishing is public. Then
  `python3 scripts/deploy.py deploy --project <name> --name <site-name>`.
  Reusing the same site name updates the same live URL every time, so
  iterating keeps one link. If it exits 3, start the Netlify login flow
  above and retry after the student signs in.
- Export: `python3 scripts/workspace.py export --project <name>` writes a
  clean zip to `/workspace/your_files/<name>.zip`; then send that zip back
  to the student in the chat with your files and media ability. No account
  needed for any of this.
- When a report is too long for a text, write it as a document and send
  that instead.

## Workflow: Undo a change

When the student says "go back" or "undo that":

1. `python3 scripts/workspace.py inspect --project <name>` to see the
   checkpoint history and say what the last change was.
2. `python3 scripts/workspace.py undo --project <name>` rolls the
   workspace back to the previous checkpoint and reports what was undone.
3. Re-run the check if the student wants to keep working after the
   rollback. Confirm with the student before undoing more than one
   checkpoint.

## Workflow: Watch repo CI (recurring)

1. Single check: `python3 scripts/monitor.py check --repo <owner/repo>`
   - exit 0 means nothing changed; exit 2 means CI flipped between
   passing and failing and prints an alert with the workflow, branch,
   commit, and run URL.
2. Recurring watch: ask the student first, agree on how often (suggest
   every 15-30 minutes), then create a scheduled check-in that runs the
   check. On exit 2, text the alert summary right away; if the student
   asked to be called, place a phone call with the same summary.
3. Public repos need no token; private repos use the saved GitHub token.

Always ask before scheduling recurring check-ins or phone calls.

## Script reference

All commands run with `python3` from this skill's folder, and every script
supports `--sample` for an offline demo with no state changes:

- `scripts/workspace.py init|inspect|write|undo|export|pr --project <name> [...]`
- `scripts/runner.py check --project <name>`
- `scripts/deploy.py status | deploy --project <name> --name <site-name>`
- `scripts/monitor.py check --repo <owner/repo>`

## Exit codes

| Script | Code | Meaning and what to do |
|---|---|---|
| workspace.py | 0 | Done; report the summary it printed. |
| workspace.py | 2 | Bad arguments, or the workspace already exists; re-check the flags. |
| workspace.py | 3 | No workspace with that name; init it first. |
| workspace.py | 4 | Local git failed; inspect the workspace, then retry. |
| workspace.py | 5 | Import failed; ask for the folder or zip again. |
| workspace.py | 6 | Clone failed; check the URL and whether the repo is private. |
| workspace.py | 7 | No GitHub token saved; ask the student to save one via secure input. |
| workspace.py | 8 | Push or pull request failed; check access and the remote URL. |
| workspace.py | 9 | Zip export failed; check disk space and retry. |
| runner.py | 0 | All checks passed; safe to deploy or ship. |
| runner.py | 2 | Bad arguments; re-check the flags. |
| runner.py | 3 | No workspace with that name; init it first. |
| runner.py | 4 | A check failed; read the stage and error tail, fix the file, re-run. |
| runner.py | 5 | Nothing recognizable to verify; ask what kind of project it is. |
| deploy.py | 0 | Deployed; report the live URL. |
| deploy.py | 2 | Bad arguments or nothing publishable; build or fix the project first. |
| deploy.py | 3 | Netlify sign-in needed; start the login link, then retry. |
| deploy.py | 4 | Netlify command failed; read the message, often a taken site name. |
| monitor.py | 0 | No change; nothing to report. |
| monitor.py | 2 | CI transition; send the alert, or place the agreed call. |
| monitor.py | 3 | Repo not found or no access; check the name or the saved token. |
| monitor.py | 4 | GitHub API failed; retry on the next check-in. |
| monitor.py | 5 | Invalid arguments; re-check the repo format. |

## If something fails

Fix it yourself when the failure is in the student's code (runner.py
exit 4): read the failing stage, correct the file, write it, re-run - at
most three rounds before you summarize what is stuck. For anything that
needs the student (sign-in, token, a yes before publishing or pushing),
ask plainly and wait. Keep every reply short: one idea per message, links
on their own line.
