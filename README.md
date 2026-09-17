# buildwork

Run a repository's open issues as parallel agents - one per issue, each in its own worktree, each opening its own pull request - then check the results and propose a merge order.

An agent skill for [Claude Code](https://code.claude.com) and [Codex](https://developers.openai.com/codex/cli). Install it, tell it what you are trying to get done today, and it works out what can safely run at once.

```
Goal: get the deploy pipeline unblocked
Runner: paseo, up to 4 at once, cut from main. Order from roadmap.md.

Wave 1 (2 in parallel):
  #143  The GitHub metadata register has drifted  [hotspot: .github/workflows/deploy.yml]
      buildwork/issue-143-the-github-metadata-register
  #147  Stale reference in the hosting doc
      buildwork/issue-147-stale-reference-in-the-hosting

Wave 2 (alone):
  #144  Positioning changed on the landing copy
      buildwork/issue-144-positioning-changed-on-the

! #151 waits a wave: it touches .github/workflows/deploy.yml, already claimed in this wave.
~ No dependency links were readable, so these issues are treated as independent.
```

## The part that matters

Several tools already run coding agents in parallel over git worktrees. They isolate the agents and then leave task alignment, conflict resolution and merge decisions to you. They are session managers.

Worktrees solve exactly one problem: two agents writing the same file at the same time. They do nothing about **the file every branch has to touch** - the route registry, the response headers, the lockfile, the content plan. Isolation just defers the pile-up to merge time.

buildwork's job is the layer above isolation:

- **It refuses.** One issue, or several issues that are really one piece of work, gets a `DO NOT FAN OUT` and a reason. A single agent matches or beats a multi-agent system on most tasks, at roughly a fifteenth of the tokens. The commonest mistake this tool can prevent is using it.
- **It serialises collisions.** Two issues that claim the same file never share a wave.
- **It checks before it hands anything over.** Scope, hotspots and your own test suite, then an honest statement that mechanical checks are a floor and not a verdict.
- **It never merges.** It proposes an order and gives its reasons. There is no merge verb in the codebase.

## Install

**Claude Code**

```bash
git clone https://github.com/dbhq-uk/buildwork-skill.git
cd buildwork && ./install.sh
```

**Codex**

```bash
./install-codex.sh
```

**As a plugin**

```
/plugin install buildwork@dbhq
```

Needs `git`, an authenticated `gh`, and Python 3.11 or later. No packages, no venv.

## Opt in, per repository

buildwork does nothing at all until a repository has a `.github/buildwork.toml` saying `enabled = true`. Write a starter:

```bash
python3 ~/.claude/skills/buildwork/scripts/buildwork.py init
```

It suggests hotspots from the files most often touched in recent merges, and writes `enabled = false`. Arming it is your edit, deliberately.

Full field reference: [`references/config.md`](skills/buildwork/references/config.md).

## How a session goes

1. **It asks what you are trying to get done.** Every time. The goal filters the roadmap, which is what stops you paying for five agents doing work you did not want today.
2. **It plans**, and shows you the waves, the collisions and the assumptions. Nothing is created until you approve.
3. **It dispatches** wave one - a Paseo tab or a host subagent per issue, each with a self-contained brief and a shared digest of your conventions read once rather than five times.
4. **It goes idle.** No polling. The finish notification arrives on its own.
5. **It collects** - scope, hotspots, your test suite - and offers exactly one rework per failure before handing it to you.
6. **It proposes a merge order**, with a line of reasoning per position. You merge.

## Runners

| | paseo | subagent |
|---|---|---|
| Survives your session | yes | no |
| You can watch and intervene | yes | no |
| Concurrent cap | 4 | 2 |
| Resume after a crash | yes | yes |

Resume works on both because it is reconstructed from git branches, open pull requests and worktrees - never from a cached map of agent ids. `status` is correct from a cold start with no session record at all.

[`references/runners.md`](skills/buildwork/references/runners.md) has the exact calls, and why detached CLI workers were rejected.

## What it does not do

- **It does not merge.** No `gh pr merge`, no push to base.
- **It does not close issues.** A worker's pull request carries `Closes #N`; GitHub closes it when a human merges.
- **It does not catch semantic conflict.** Agent A writes a helper, agent B changes its signature, neither branch is broken alone and the merge is. That is caught by your test suite or by you. Mechanical QC is a floor, and the tool says so rather than implying otherwise.
- **It does not draw a dashboard.** Paseo is better at that.
- **It does not run on a schedule.** Every pass is on demand.

## The pair

`buildwork` runs the work. [`deskwork`](https://github.com/dbhq-uk/deskwork-skill) decides what the work is and what order it goes in - it files issues, reasons about precedence, writes dependency edges back to GitHub, and renders `roadmap.md`.

Neither needs the other. buildwork reads issues and a roadmap file whoever wrote them, and falls back to open issues in no particular order while saying so.

## Licence

MIT. See [LICENSE](LICENSE).
