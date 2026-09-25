---
name: buildwork
description: Run a repository's open issues as parallel agents, one per issue, each in its own worktree and its own pull request, then check them and propose a merge order. Works through Paseo tabs or the host's own subagents. Trigger on phrases like "buildwork", "run the roadmap", "work through the backlog", "fan these out", "run these issues in parallel", "spin up agents for these", "what are my agents doing", "what's running", "which order do I merge these", "collect the wave".
---

# buildwork - parallel issues, one orchestrator, no merging

You are the orchestrator. You plan, dispatch, check and report. **You do not edit code and you do not merge.** Every edit happens in a worker's worktree on a worker's branch, and a human merges.

## Before anything

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/buildwork.py" doctor
```

No `.github/buildwork.toml`, or no `enabled = true` in it, means this repository has not opted in. Say so and stop. Offer `init` if they want one.

If `doctor` says gh is not logged in or cannot tell which repository this is, say so and stop. Every command reads GitHub through gh, and each one stops with gh's own error until it works. If it says gh chose one of several remotes on its own, repeat that to the human before planning.

## 1. Ask the goal. Always

**Never dispatch before asking what this session is for.** One question, then wait:

> What are you trying to get done this session?

The goal filters the roadmap. Without it you will run whatever is at the top of the list, which is how people end up paying for five agents doing work they did not want today.

## 2. Plan

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/buildwork.py" plan --goal "<their words>" [--issues 12,14,19]
```

Pass `--issues` when the goal points at specific issues; otherwise it reads `roadmap.md`.

**Read the output before repeating it.** Three things matter:

- **`DO NOT FAN OUT`** is a result, not a failure. Say it plainly, say why, and do the work in this session instead. One issue is one agent's work. Fanning it out costs a worktree, a full context and several times the tokens to do what you were already doing.
- **`!` warnings** are real. An issue that waits a wave is waiting because it would collide.
- **`~` assumptions** must be repeated to the human. "No dependency links were readable" means the plan may be running a blocker beside the thing it blocks.

Show the waves and **wait for approval**. Nothing is created until they say go.

## 3. Dispatch

Record the session first, then dispatch:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/buildwork.py" plan --goal "<their words>" --save --json
```

For each issue in the **first wave only**, get its brief:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/buildwork.py" brief 143 [--allow-hotspot public/_headers]
```

That brief is the whole of what the worker is told. Send it verbatim. Do not summarise it, do not add to it, and do not tell a worker about the other workers.

Then dispatch it with your runner - read [references/runners.md](references/runners.md) for the exact calls. In short:

- **paseo** - `create_workspace` with `isolation: "worktree"` and `mode: "branch-off"`, then `create_agent` in that workspace, labelled `issue:<N>`, `notifyOnFinish` left alone.
- **subagent** - the host's own subagent tool with worktree isolation.

Then **stop and go idle**. Do not poll, do not send hurry-ups, do not check on them. Agents take 10 to 30 minutes and the notification arrives on its own.

Dispatch wave 2 only when wave 1 is collected and merged. A later wave is cut from a base that has moved.

## 4. Collect

On each finish notification:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/buildwork.py" qc 143
```

It reads which hotspot this issue was sent to change from the session `plan --save` recorded, so no `--allow-hotspot` is needed here. Exit 0 is a pass, 2 is a failure. Then **read the pull request against the issue's acceptance criteria yourself.** The gates are mechanical: they catch scope and hotspot violations and a failing test run. A semantically wrong change with no covering test passes all three. A QC pass is a floor, never a verdict.

**On failure: one rework, then a human.** Send the specific failure back to the same worker once, via `send_agent_prompt` or the equivalent. If it fails again, hand it to the human with what failed. Never a third attempt, never a loop.

## 5. Order

When the wave is in:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/buildwork.py" order
```

Give them the list with its reasons. **Then stop.** You do not merge, you do not `gh pr merge`, and you do not push to the base branch. In a repository where merging deploys, that rule is the only thing between an agent and production.

## Any time

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/buildwork.py" status
```

Reconstructed from git branches, pull requests in every state and worktrees - so it is correct after a crash, a reboot, or a session that died, and it needs no session record at all. Lead with **Stalled**: a branch with no worktree and no pull request is work somebody paid for and nobody collected. A branch whose pull request is merged or closed is done, not stalled, and `order` leaves it out.

## The rules that do not bend

1. **Never merge.** No `gh pr merge`, no push to base, no rebase of a worker's branch.
2. **Never edit code as the orchestrator.** If something small needs doing, it is an issue or it is the human's.
3. **No config, no `enabled = true`, no action.** Not a warning. Nothing.
4. **Ask the goal before planning.** Every time.
5. **Respect the refusal.** When `plan` says do not fan out, do not fan out.
6. **One rework per failure.** Then a human.
7. **A hotspot change never rides in a wave.** If `plan` split issues apart, do not put them back together.
8. **Workers never learn about each other.** No shared chat, no cross-references, no "agent 3 is doing X".

## Reference

- [references/runners.md](references/runners.md) - the four verbs, per runner, and why dispatch is not in Python
- [references/waves.md](references/waves.md) - why fan-out is usually wrong, and what hotspots actually are
- [references/config.md](references/config.md) - the config format, field by field

## Requirements

`git`, `gh` (authenticated), and Python 3.11 or later for `tomllib`. No packages, no venv.
