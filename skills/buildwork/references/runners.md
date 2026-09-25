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
| `status` | the finish, error and permission notifications | the subagent's result; permission prompts appear in your session |
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

### When a worker stalls

`notifyOnFinish` covers three events, not one: the agent **finished**, it
**errored**, or it **needs permission**. SKILL.md says what to do with each. A
permission request is read with `list_pending_permissions` and answered with
`respond_to_permission`, and only with the human's decision, unless the request
is one the brief forbids, which you deny.

An agent can also die without any of them, and its worktree stays behind. So
`status` takes the runner's word for who is working:

1. Call `list_agents` once, when the human asks or the watchdog fires. One
   read at a time of asking is not polling.
2. Keep the agents whose `labels` has an `issue`.
3. Of those, the ones whose `status` is `initializing` or `running` are
   working. `idle`, `error` and `closed` are not.
4. Run `status --live 12,14` with their issue numbers, or `status --live none`.

A worktree whose issue is not in the list is **stalled**, not running. Nothing
is stored: the list is read when you ask and thrown away, so it is never stale.

For a safety net against an agent that dies without a word, set one watchdog
per wave before you go idle:

```
create_heartbeat(
  name: "buildwork watchdog",
  cron: "<minute> <hour> * * *",
  timezone: "UTC",
  maxRuns: 1,
  prompt: "buildwork watchdog: call list_agents once and run buildwork.py status --live with the issues that have a working agent",
)
```

Set `cron` to the time 45 minutes from now, in that zone: at 14:20 UTC, that is
`"5 15 * * *"`. `maxRuns: 1` makes it fire once, so it is not polling. If the
wave is in before it fires, remove it with `delete_heartbeat`.

### Re-dispatch

A stalled issue has a branch, often with commits on it. **Put the new worker on
that branch.** Never cut a fresh one: that throws the work away and leaves two
branches for one issue, and the join key stops being unique.

Re-dispatch only when the old agent is gone - `closed`, or not listed at all.
An agent that is still listed, idle or errored, gets one `send_agent_prompt` to
carry on instead. Either way, it is that worker's one rework.

If `status` still shows a worktree on the branch, the old workspace is still
there. Find its `workspaceId` with `list_workspaces`, matching `cwd` to that
worktree, and create the new agent in it. If the worktree is gone, check the
branch out into a new one:

```
create_workspace(
  isolation: "worktree",
  mode: "checkout-branch",
  branch: "buildwork/issue-143-metadata-register",
)
```

Then `create_agent` exactly as for a first dispatch, with the brief from
`brief 143 --runner paseo --branch <the branch status shows>`. `brief` sees
the commits already on the branch and tells the worker to build on them rather
than start again.

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

### A stalled subagent

There is no re-dispatch onto a stalled branch under this runner. The host
always makes a new branch for a worktree subagent, so a second worker cannot
be put on the first one's work, and the brief's rename onto a name that
exists fails at its first step. Hand the branch to the human with what
`git log origin/<base>..<branch>` shows: they can finish it by hand,
re-dispatch it under Paseo, or delete the branch so the next plan starts it
fresh.

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
