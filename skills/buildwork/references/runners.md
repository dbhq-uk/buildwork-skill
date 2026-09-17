# Runners

A runner is the thing that actually starts an agent in a worktree. buildwork
supports two, and almost nothing in the skill depends on which one you have.

## Why dispatch is not in Python

`buildwork.py` never starts an agent. It cannot: dispatch goes through MCP
tools or the host's own subagent surface, and a subprocess has access to
neither. So the split is deliberate:

- **Python** does every deterministic part - config, roadmap parsing, hotspot
  detection, wave planning, briefs, QC gates, merge ordering. All of it is
  tested without a network, a token or an agent.
- **You** do dispatch and judgement, following this file.

The useful consequence is that the interesting logic is testable and the
untestable part is small enough to read.

## The four verbs

| Verb | paseo | subagent |
|---|---|---|
| `dispatch` | `create_workspace` then `create_agent` | the host's subagent tool, worktree isolation |
| `list` | `list_agents`, filtered by label | nothing survives; reconstruct instead |
| `status` | the finish notification | the tool's own return value |
| `collect` | read the pull request | read the pull request |

`collect` is identical because the result of a worker is a branch and a pull
request, not a chat transcript. That is the whole reason resume works.

## paseo

Create the workspace first, then the agent in it.

```
create_workspace(
  isolation: "worktree",
  mode: "branch-off",
  branchName: "buildwork/issue-143-metadata-register",
  baseBranch: "main",
)
```

Then, with the returned `workspaceId`:

```
create_agent(
  title: "[buildwork] #143 The metadata register has drifted",
  provider: "<from list_profiles>",
  workspaceId: "<from create_workspace>",
  labels: ["buildwork", "issue:143"],
  initialPrompt: "<the output of buildwork.py brief 143, verbatim>",
)
```

**Call `list_profiles` first** and pick the profile whose `notes` match
implementation work. Materialise it into `create_agent` - combine `provider`
and `model` into `provider`, copy `modeId`, `thinkingOptionId` and
`featureValues` into `settings`. There is no `profile` parameter.

**The `issue:<N>` label is not decoration.** It is how `list_agents`
reconstructs which tab is on which issue after your context is gone. Always
set it, always in that exact form.

Leave `notifyOnFinish` alone - agent-scoped `create_agent` defaults it to true,
which is what you want. Then go idle. **Do not poll `list_agents` or
`get_agent_status` to check on a running agent.** The notification arrives on
its own, and polling burns tokens to learn nothing.

For the one bounded rework, use `send_agent_prompt` against the same
`agentId` with the specific failure. Once.

## subagent

Use the host's own subagent tool with worktree isolation. In Claude Code that
is the Agent tool with `isolation: "worktree"`.

Worth being straight about what you lose:

- **The wave cap drops to 2.** A host subagent is not supervised, cannot be
  watched mid-run, and cannot be intervened in.
- **Nothing survives the session.** If your session dies, the agents die with
  it. The branches and pull requests do not, which is why resume is built on
  those and not on agent ids.
- **There is no `list`.** `buildwork.py status` reconstructs from git and
  GitHub instead, which is correct anyway.

Everything else - the brief, the QC gates, the merge order - is unchanged.

## What was rejected, and why

**Detached CLI workers** - `git worktree add`, then `claude -p` or `codex exec`
in the background with output to a log. Genuinely universal, survives the
session, and would run from cron.

It is not shipped because permission prompts have nowhere to go. Every worker
would need skip-permissions or full-access mode, which means a public skill
whose happy path is an unsupervised agent with write access to a repository.
That is a decision for a human to make deliberately in their own tooling, not a
default to install.

## Adding a runner

Implement the four verbs and nothing else. If a change needs to reach into
wave planning, the brief, or the QC gates, the boundary is in the wrong place -
those are runner-independent by design and every runner benefits from keeping
them that way.
