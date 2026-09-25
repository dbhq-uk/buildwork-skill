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
| `list` | `list_agents`, then keep the agents whose `issue` label matches | `/tasks`, this session only; reconstruct instead |
| `status` | the finish notification | the finish notification |
| `collect` | read the pull request | read the pull request |

`collect` is identical because the result of a worker is a branch and a pull
request, not a chat transcript. That is the whole reason resume works.

## paseo

Create the workspace first, then the agent in it. Take `branch` and `base_ref`
from the plan you just ran (`plan --json`), not from memory.

```
create_workspace(
  isolation: "worktree",
  mode: "branch-off",
  branchName: "buildwork/issue-143-metadata-register",
  baseBranch: "origin/main",
)
```

**`baseBranch` is always `origin/<base>`, never a bare `main`.** Paseo resolves a
bare name to the local branch when one exists, and a local `main` is wherever
this clone last pulled. After wave 1 merges on GitHub, that is a base without
wave 1 in it. `plan` fetches `origin/<base>` before it prints anything, and
names it as `base_ref`, so the ref is current when you dispatch.

Then, with the returned `workspaceId`, and the brief from `brief 143 --runner paseo`:

```
create_agent(
  title: "[buildwork] #143 The metadata register has drifted",
  provider: "<provider>/<model>, from list_profiles",
  workspaceId: "<from create_workspace>",
  labels: {"buildwork": "1", "issue": "143"},
  settings: {
    modeId: "<from the profile>",
    thinkingOptionId: "<from the profile>",
    features: <the profile's featureValues>,
  },
  initialPrompt: "<the output of buildwork.py brief 143, verbatim>",
)
```

`title` is at most 60 characters; cut the issue title to fit. `labels` is a map
of string to string, not a list. Leave out any `settings` field the profile
does not set.

**Call `list_profiles` first** and pick the profile whose `notes` match
implementation work. There is no `profile` parameter, so copy it across by
hand: its `provider` and `model` together make `provider`, and its `modeId`,
`thinkingOptionId` and `featureValues` go into `settings` as `modeId`,
`thinkingOptionId` and `features`.

**The `issue` label is not decoration.** It is how you find which agent is on
which issue after your context is gone. `list_agents` cannot filter by label:
it takes only `cwd`, `statuses`, `sinceHours`, `includeArchived` and `limit`.
So call it once and keep the agents whose `labels` has `"issue": "143"`. Always
set both labels, always in that exact form.

Leave `notifyOnFinish` alone - agent-scoped `create_agent` defaults it to true,
which is what you want. Then go idle. **Do not poll `list_agents` or
`get_agent_status` to check on a running agent.** The notification arrives on
its own, and polling burns tokens to learn nothing.

For the one bounded rework, use `send_agent_prompt` against the same
`agentId` with the specific failure. Once.

### Later waves

**Run `plan` again before every wave after the first**, with the issues that
are left, and dispatch from that output. Never dispatch a later wave from the
plan you saved at the start. By then the base has moved: `plan` fetches it
again, and the merged work can change which issues collide.

## subagent

Use the host's own subagent tool with worktree isolation. In Claude Code that
is the Agent tool with `isolation: "worktree"`. Get each brief with
`brief <N> --runner subagent` and send it verbatim as the prompt.

### What the host does to the worktree

- **It names the branch itself.** A Claude Code worktree subagent works on a
  branch called `worktree-agent-<id>`, not `buildwork/issue-<N>-<slug>`. The
  Agent tool returns that name as `worktreeBranch`; the name is not
  documented anywhere else.
- **It cuts the worktree from `origin/<default branch>`**, whatever `base`
  says, and refreshes that ref only when it is more than 24 hours old
  ([sub-agents](https://code.claude.com/docs/en/sub-agents),
  [worktrees](https://code.claude.com/docs/en/worktrees)).

So the subagent brief opens with three steps, before the task: rename the
branch to the buildwork name, check the name took, and check that `HEAD` is
the same commit as `origin/<base>`. If a check fails, the worker stops and
says so before it changes anything. `plan` has just fetched `origin/<base>`,
so a worker cut from the right base passes; one cut from `main` when `base`
is `develop` does not.

Once renamed, the branch is found by `qc`, `order` and `status` like any
other. If a worker stopped before the rename, collect it by the name the Agent
tool returned: `qc <N> --branch <worktreeBranch>`. Keep that name when you
dispatch.

### What a Claude Code subagent can do today

- **It runs in the background** and notifies you when it finishes, so you go
  idle exactly as with Paseo.
- **Its permission prompts appear in your session**, and you answer them there.
- **You can message it** with `SendMessage`, which is how the one bounded
  rework is sent, **stop it** with `TaskStop`, and **list what is running**
  with `/tasks`.

### What you still lose against Paseo

- **Nothing survives the session.** If your session dies, the agents die with
  it. The branches and pull requests do not, which is why resume is built on
  those and not on agent ids.
- **The wave cap stays at 2.** Every worker's permission prompts land in the
  session you are orchestrating from, and none of them outlives it.
- **There is no `list` that outlives the session.** `/tasks` covers this
  session only; `buildwork.py status` reconstructs from git and GitHub, which
  is correct anyway.

Everything else - the QC gates, the merge order - is unchanged.

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
