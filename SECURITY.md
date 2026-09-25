# Security

## Reporting a vulnerability

Email <dan@dbhq.uk> rather than opening a public issue. Include what you found,
how to reproduce it, and what an attacker could do with it. You will get a first
response within 48 hours.

## What this skill does

buildwork plans parallel agent work, checks finished branches, and proposes a
merge order. The scripts do the deterministic half; the agent following
`SKILL.md` does dispatch. Both halves are described here, because the answer to
"what can this touch" is different for each.

### Credentials

**None are handled, stored, or read.** `gh auth` is the credential and `gh`
holds it. There is no config file for a token, no environment variable, no
keyring entry, and nothing in `~/.dbhq/buildwork/` but a session record holding
a goal, a list of issue numbers, the hotspot paths each issue was sent to
change, and a timestamp.

That directory is created `700` and the record `600`, in line with the DBHQ
convention that a skill keeps its state in `~/.dbhq/<skill>/`.

### Network

**Only through `gh`, and only reads.** Every call is `gh issue list`,
`gh issue view`, `gh pr list` or `gh api ... /dependencies/blocked_by`, plus
`gh auth status` and `gh repo view` from `doctor`. The
scripts never open a socket themselves and never send a request anywhere that
is not GitHub via a CLI you already trust.

### Writes to your repository

The scripts write in exactly these places:

- `.github/buildwork.toml`, and only from `init`, and only with
  `enabled = false`. `init` refuses to overwrite an existing config without
  `--force`.
- The remote-tracking ref `origin/<base>`, which `plan` and `order` fetch.
  No local branch moves.
- The object store, from `order`'s conflict check. `git merge-tree
  --write-tree` and `git commit-tree` write the trees and commits of trial
  merges. No ref points at them, and git's garbage collection removes them.
- Nothing else. No branch is created, deleted, checked out, pushed, merged or
  rebased by any script in this repository.

Workers write to their own worktrees. That is the agent's doing under the
host's permission model, not the script's.

### Command execution

One place: the `gate` command from `.github/buildwork.toml`, run with
`shell=True` in the worker's worktree, with a 30 minute timeout.

**This is arbitrary code execution by design** - it is your test suite. It
comes from a file committed to the repository, so it carries exactly the trust
you already extend to anything else in that repository: a `Makefile`, a
`package.json` script, a CI workflow. Treat a pull request that changes `gate`
the way you would treat a pull request that changes your CI.

If that trust is not appropriate for your repository, leave `gate` unset.
`doctor` will tell you nothing mechanical is verifying branches, which is true
and is the tradeoff.

### What it cannot do

- **It cannot merge.** There is no merge verb in the codebase, and
  [`AGENTS.md`](AGENTS.md) makes adding one a broken constraint rather than a
  feature request. In a repository where merging deploys, this is the
  load-bearing one.
- **It cannot close or delete an issue.** No close verb either.
- **It cannot act without opt-in.** No `.github/buildwork.toml`, or no
  `enabled = true` inside it, and every command stops at the config load.

## Supply chain

Python standard library only. No PyPI packages, no `requirements.txt`, no venv,
no lockfile - which is why Dependabot here watches GitHub Actions and nothing
else. The two runtime dependencies are `git` and `gh`, both of which you
installed and both of which hold their own credentials.
