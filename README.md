# cubbie coding harness
Cubbie can write code. But it can't plan real projects, build and test them, and host them. I turned Cubbie (a chatbot) into a full coding agent.

# Core Problems Addressed

Cubbie's sandbox is just to run code scripts to get outputs. It cannot build projects and give you the output files. I wanted to turn a chatbot into a coding agent, so I built a harness around the chatbot that can manage files, make git commits and hosting, etc. Basically, if Claude is Cubbie, I build a Claude Code for Cubbie.

Build websites and apps through text messages. You describe what you want, the harness writes the code, runs the checks, and puts it live on the internet. No coding knowledge required.

## What it does

You tell it what to build in plain language — "a portfolio site," "a page for my club," "fix this broken page." It scaffolds the project, writes the files, checks that everything works, and deploys it to a live URL you can send to anyone.

Every change is saved as a checkpoint, so you can undo anything at any time. Nothing is lost when the conversation ends.

## How it works

1. **Say what you want.** Describe the site or app in a sentence or two.
2. **It builds.** The harness creates the project from a template and writes the code.
3. **It checks.** It runs tests on the code and tells you if something is broken.
4. **It goes live.** One command puts it on the internet with a shareable link.
5. **You keep it.** Export the whole thing as a zip file, or push it to GitHub.

No accounts are needed to start. You only sign in if you want to deploy live or push to GitHub.
