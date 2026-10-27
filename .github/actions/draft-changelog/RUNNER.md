# The `changelog-agent` runner

`release-open.yml` drafts each release's changelog with Claude Code running on a
self-hosted GitHub Actions runner labelled `changelog-agent`. This page covers
setting that runner up. You need admin on `sciencecorp/synapse-python` to
register it.

## What runs there

Only the `draft-changelog` job of `release-open.yml`. It checks out `main`
without a token, then runs `draft_changelog.py`, which calls `claude -p` with
read-only tools: `git log`, `git show`, `git diff`, Read, Grep and Glob. It
loads no settings, hooks or MCP servers from the box, and stops at $5 or 9
minutes (the job is capped at 10). The changelog goes back to GitHub as a workflow artifact; the version
bump, push and PR happen on GitHub-hosted runners.

If `claude` is missing or fails, the job still succeeds and the release PR gets
a plain list of commit subjects instead. If the runner is offline, the PR job
waits 10 minutes for the draft, then opens the PR with commit subjects and
cancels the queued draft job (so the run shows as cancelled).

## Why this needs care

This repo is public. Anyone can open a pull request, and a pull request can
change workflow files. A workflow that runs on `pull_request` with
`runs-on: [self-hosted, changelog-agent]` would run their code on this machine.
So:

- Use the `changelog-agent` label only in `release-open.yml`, which only runs
  when someone with write access starts it by hand. Never add it to a workflow
  triggered by `pull_request`, `push` or `issue_comment`.
- In Settings → Actions → General, under "Fork pull request workflows from
  outside collaborators", choose **Require approval for all outside
  collaborators**.
- Run the runner as its own unprivileged user on a machine that holds nothing
  else sensitive. The Claude login on it is the only secret it needs.

## Setup

On the machine (Linux x64):

1. Create a user for the runner, e.g. `sudo useradd -m changelog-runner`, and
   do everything below as that user.
2. Install Claude Code and log it in with the account that should pay for the
   changelogs:

   ```bash
   curl -fsSL https://claude.ai/install.sh | bash   # installs ~/.local/bin/claude
   claude setup-token                               # prints a long-lived token
   ```

   Put the token in the runner's environment (step 4) as
   `CLAUDE_CODE_OAUTH_TOKEN`. `claude setup-token` needs a Claude subscription.

3. In GitHub, Settings → Actions → Runners → **New self-hosted runner** → Linux.
   Follow its download commands, then configure with the label:

   ```bash
   ./config.sh --url https://github.com/sciencecorp/synapse-python \
     --token <token from that page> \
     --name changelog-agent-$(hostname) \
     --labels changelog-agent \
     --unattended
   ```

4. Give the runner service `claude` and the token. In the runner directory:

   ```bash
   echo "PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" >> .env
   echo "CLAUDE_CODE_OAUTH_TOKEN=<token from step 2>" >> .env
   chmod 600 .env
   ```

5. Install and start it as a service:

   ```bash
   sudo ./svc.sh install changelog-runner
   sudo ./svc.sh start
   ```

## Check it

The runner shows as Idle under Settings → Actions → Runners. Then run
Actions → release-open → Run workflow. In the run, the `draft-changelog` job's
"Draft changelog" step prints the changelog. If it printed only commit
subjects, the step's warning says why (usually `claude` not on `PATH`, or not
logged in). Close the PR it opens if you didn't mean to release.

Python 3.9 or newer and git must be installed on the machine.
