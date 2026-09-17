# buildwork - design

**Date:** 2026-09-17
**Status:** design agreed, build starting
**Repo:** `dbhq-uk/buildwork` (public, to be created), to be checked out at `~/dbhq-uk/buildwork`
**Licence:** MIT

## What it is

An agent skill that takes the ordered work on GitHub, hands each piece to a separate agent in its own worktree, and brings the results back in an order that does not fight itself.

It is the execution half of a pair. `deskwork` decides **what** and **in what order**: it files issues, reasons about precedence, writes the dependency edges back to GitHub as native links, and renders `roadmap.md`. `buildwork` **runs** it. Neither needs the other to exist - `buildwork` reads issues and a roadmap file, whoever wrote them - but together they are the whole loop, and the `-work` suffix now names a system rather than a coincidence.

## Why this, and why now

Four tools already run several coding agents in parallel over git worktrees: Claude Squad, Conductor, Crystal and Vibe Kanban. They share one mechanic and one gap. Every one of them isolates agents and then leaves task alignment, conflict resolution and merge decisions to the human. They are session managers, not coordination layers.

Paseo already provides the substrate those tools exist to provide - workspaces, worktree isolation, agent tabs, finish notifications, labels. There is nothing to rebuild. What is missing above it is the layer nobody ships: deciding what may safely run at once, what must not, what to do with five finished branches, and when not to fan out at all.

## Non-goals

Each is a maintenance obligation, a safety problem, or somebody else's job.

- **Merging.** `buildwork` never merges and never completes a pull request. It proposes an order and gives its reasons. See the constraints.
- **Being a session manager.** It does not draw a dashboard, tail a log, or replace the Paseo UI. Paseo is better at that than anything this skill would render.
- **Being a git tool.** Worktree creation goes through the runner. Branch housekeeping is `gitview`, which already exists.
- **Closing issues.** Same line `deskwork` and `jira` hold. A worker's pull request carries `Closes #N`, a human merges, GitHub closes the issue.
- **Scheduled sweeps.** No nightly run, no automatic dispatch. `CLAUDE.md` in `dbhq` forbids proposing scheduled reviews, and every pass here runs on demand.
- **A hosted component, an account, or telemetry.**

## Decisions taken, and why

| Decision | Choice | Reason |
|---|---|---|
| Where work comes from | GitHub issues, ordered by `roadmap.md` | Coordination state in the working tree becomes its own merge surface once several agents write to it. GitHub is off the tree and survives a crash |
| Roadmap location | `roadmap.md` in the repo root | Dan, 17 Sep 2026. Supersedes the `docs/roadmap.md` default in the deskwork design, which is amended in the same pass |
| Orchestrator edits | Never | A thin orchestrator that classifies, delegates and collects is the whole trick. One that also codes is the monolith one level up |
| Integration | One pull request per worker, `buildwork` proposes merge order, a human merges | Matches `deskwork`, which deliberately has no close verb. In `dbhq` a merge to `main` is the deploy, so an unreviewed agent branch would ship live |
| Runners | Two: `paseo` and `subagent` | The repo is public and most adopters will not have Paseo, so the portable path is the majority path, not a fallback |
| Portable runner | The host's own subagent tool with worktree isolation | Permissions, sandboxing and cost controls stay the harness's problem, which is where they belong. Detached CLI workers were rejected: permission prompts have nowhere to go, so every worker needs skip-permissions, and that is not a default to ship publicly |
| Resume | Reconstructed from git branches, open pull requests and the board | Identical on every runner, and correct after a crash, a reboot or a closed laptop. A cached map can disagree with reality; this cannot |
| Session state | Only the goal and the wave, in `~/.dbhq/buildwork/` | The session goal is the one thing the runner and GitHub cannot reconstruct. `CLAUDE.md` puts skill state in `~/.dbhq/<skill>/`, never in the working tree |
| Configuration | A committed `.github/buildwork.toml`, requiring `enabled = true` | Same gate, same file location and same reasoning as `deskwork`. Two skills, one convention |
| Language | Python standard library, shelling out to `gh` and `git` | Matches `gitview` and `deskwork`. No packages, no venv |
| Repository | Public, `dbhq-uk/buildwork` | The coordination rules are the interesting part and are worth nothing unless others can adopt them. All the prior art is public |

## The shape

One orchestrator, N workers, no worker-to-worker contact.

**Orchestrator** - the session you are already in, on `main` or in its own worktree, either works. It never edits code. It interviews you for the session goal, reads `roadmap.md`, picks the issues that serve that goal, plans a wave, dispatches, waits, collects, and proposes a merge order.

**Workers** - full agents in isolated worktrees branched from `base`. Each gets one issue, the shared digest and a scoped brief. Each opens its own pull request carrying `Closes #N`. They never see each other, and they are never told about each other.

**Shared digest** - the common context, read once by the orchestrator and shipped into every worker's initial prompt: the repo conventions, the invariants, and the files every worker in this wave will need. Taken from CoalFace. Without it, five agents each re-read `CLAUDE.md` and the same four files, and the token bill is the reason people abandon fan-out.

**Collection** - on each finish, the orchestrator reads the pull request, runs the QC gates, and holds it. When the wave is in, it works out merge order and hands over the list with reasons.

## Hotspots, which is the part that matters

Worktrees isolate files. They do not isolate meaning, and they do nothing at all about a file every branch touches.

`hotspots` in the config names the files where a parallel edit is guaranteed to conflict - route registries, `_headers`, a CSP, a content plan, a lockfile. Before planning a wave, `buildwork` reads each candidate issue and its linked spec for any hotspot path. If two issues in a wave both touch one:

1. The hotspot edit is done **first, alone**, on `base`, by the orchestrator asking you or by a single worker.
2. Only then does the wave go out, from the new `base`.

This is the one conflict class worktrees cannot help with, and it is the single thing that separates this from a session manager.

The second class - semantic conflict, where agent A writes a helper and agent B changes its signature, and neither branch is broken alone - is not solved here and is not claimed to be. It is caught at collection, by the domain gate, or not at all.

## Wave sizing, including the rule that says do not

The default failure of every tool in this category is fanning out work that one agent should simply do. A single agent matched or beat multi-agent systems on 64% of benchmarked tasks given the same tools and context, and multi-agent runs burn roughly 15x the tokens of a chat. Anthropic hard-codes effort rules into its lead-agent prompt for exactly this reason, and so does `SKILL.md` here:

- **1 issue**, or issues that all touch the same files → **no fan-out**. Say so, and do the work in this session.
- **2 to 4 independent issues** → one wave.
- **More than 4, or any `blocked-by` edge** → topologically ordered waves.
- **A fully chained set** → sequential, with no speedup. Say that plainly rather than dressing it as parallelism.
- **Cap** from `wave.max`: 4 on `paseo`, 2 on `subagent`.

The dependency edges come free. `deskwork` writes them to GitHub as native blocked-by links, so `buildwork` reads the graph rather than re-deriving it. Where there is no `deskwork`, absent edges mean the issues are treated as independent, and that assumption is stated in the plan rather than hidden.

## QC at collection, two gates

**Mechanical**, first, because it is deterministic and cheap:

- the branch's domain gate passes - the `gate:` command from the config, usually the test suite
- the diff stays inside the files the issue declared
- nothing touched a `hotspots` path without permission

**Judgement**, second: read the pull request against the issue's acceptance criteria.

A failure gets **one bounded rework** - the same worker is re-prompted with the specific failure, once. Then it comes to the human. No self-retry loops, because an agent that retries itself spends without bound.

**The honest ceiling**, and it belongs in `AGENTS.md` in these words: mechanical QC catches scope and spec violations. A semantically wrong change with no covering test passes both gates. QC is a floor, not a guarantee.

## Merge order

Reasoned, not computed, and therefore shipped with its reasons attached - the same discipline as `deskwork`'s roadmap, and for the same reason: the order will differ between runs, so it is built to be reviewed rather than believed.

1. Any pull request touching a hotspot goes first, if one got through.
2. Then dependency order from the issue graph.
3. Then smallest diff first among independents, to shrink everyone else's rebase.

Output names each pull request, its issue, and one line of why it sits where it does. The human merges.

## The config file

`.github/buildwork.toml`, committed to the repository it governs.

**TOML, not YAML**, for the reason the `deskwork` design gives: the standard library parses TOML (`tomllib`, 3.11 and later) and has never parsed YAML. A YAML config would mean a PyPI dependency or a hand-rolled parser, and a hand-rolled parser that mostly works is worse than either. The two skills share a config convention, so they share the format.

```toml
enabled = true                      # required; file presence alone arms nothing
runner = "auto"                     # auto | paseo | subagent
roadmap = "roadmap.md"
base = "main"
gate = "python3 -m pytest -q"       # the domain gate run at collection

hotspots = [
  "website/public/_headers",
  "docs/website/content-plan.md",
]

digest = ["CLAUDE.md", "AGENTS.md"]

[wave]
max = 4
```

`auto` detects: Paseo MCP tools present → `paseo`; otherwise a worktree-capable subagent tool in the host → `subagent`; otherwise refuse and say why.

`enabled = true` is required, for the same reason `deskwork` requires it: a half-written or copied-in file must not arm the skill.

## The runner boundary

Almost nothing is runner-specific. The session interview, the roadmap read, hotspot detection, wave planning, the shared digest, QC and merge ordering are all runner-independent. Four verbs cross the line:

| Verb | `paseo` | `subagent` |
|---|---|---|
| `dispatch(brief, branch)` | `create_workspace` with `isolation: worktree`, then `create_agent` labelled `issue:N`, `notifyOnFinish` left true | the host's subagent tool with worktree isolation |
| `list()` | `list_agents` filtered by label | nothing survives the session; fall through to reconstruction |
| `status(handle)` | the finish notification, never polling | the tool's own return |
| `collect(handle)` | read the pull request | read the pull request |

**This boundary lives in `SKILL.md` and `references/runners.md`, not in Python.** Dispatch happens through MCP tools or the host's own tool surface, neither of which a Python script can call. So the split is: Python does every deterministic part and is tested; the agent does dispatch and judgement, following the reference.

Resume is deliberately built below the boundary, on git branches, open pull requests and board status. It is therefore identical on both runners and survives anything.

## Modes

### `plan`

The opening move, and an interview rather than a dispatch.

1. **Ask the session goal.** What are you trying to get done. Nothing is dispatched before this is answered.
2. **Read `roadmap.md`** and the open issues it names.
3. **Filter** to what serves the goal.
4. **Detect hotspots** across the candidates.
5. **Apply the effort rules**, including the refusal to fan out.
6. **Propose the wave** - which issues, which order, which go solo first, and what is being assumed.
7. **Wait for approval.** Nothing is created until then.

### `run`

Dispatches the approved wave, then stops talking.

Builds the shared digest, writes one brief per issue, calls the runner once per issue, records the session in `~/.dbhq/buildwork/`, and goes idle. It does not poll. The paseo skill is explicit that agents take 10 to 30 minutes and that the notification arrives on its own.

### `collect`

Runs on a finish notification, or on demand.

Runs the two QC gates against the branch, reports pass or fail with the specific failure, offers exactly one rework, and holds the pull request until the wave is in.

### `order`

Proposes the merge order, with one line of reasoning per position. Never merges.

### `status`

Reconstructs the whole picture from git, GitHub and the runner, and says what is running, what is waiting on QC, what is waiting on you, and what is stalled. Correct from a cold start with no session record at all.

### `init` and `doctor`

- **`init`** writes a starter `.github/buildwork.toml` with `enabled: false`, detects the runner, and lists candidate hotspots by finding the files most often touched across recent merges. Idempotent.
- **`doctor`** reports drift: issues in progress with no branch, branches with no issue, workers finished with no pull request, hotspots named in the config that no longer exist, and a stale session record.

## Non-negotiable constraints

These belong in `AGENTS.md` in the new repository, in the same voice as `devskills`.

**1. It never merges.** No merge, no pull request completion, no rebase of somebody else's branch, no push to `base`. The skill has no merge verb at all, which is what makes the constraint hold itself rather than depend on restraint. In `dbhq` a merge to `main` is the deploy; this rule is why an agent cannot ship the site.

**2. The orchestrator never edits code.** It reads, plans, dispatches, checks and reports. Every edit happens in a worker's worktree, on a worker's branch.

**3. No config file, or no `enabled = true`, means no writes.** Not a warning, not a prompt. The skill does nothing.

**4. Never fan out below the floor.** One issue is one agent's work. The effort rules are a requirement in `SKILL.md`, not a suggestion, and the refusal is a first-class outcome that gets said out loud.

**5. One rework, then a human.** A failed QC gate is re-prompted once, with the specific failure. Never twice, never a loop.

**6. Resume is reconstructed, never cached.** State comes from git branches, open pull requests and the board. The session record holds the goal and the wave and nothing a query could answer.

**7. Hotspot edits never ride in a wave.** If two issues in a wave touch a hotspot path, the hotspot change lands alone on `base` first.

**8. No credential file.** `gh auth` is the credential, and the runner is the host's. There is nothing in `~/.dbhq/buildwork/` but a session record, nothing to leak and nothing to migrate.

## Architecture

```
.claude-plugin/plugin.json
install.sh / install-codex.sh
skills/buildwork/SKILL.md
skills/buildwork/references/
  runners.md                  # the four verbs, per runner, and why dispatch is not in Python
  waves.md                    # the effort rules, hotspots, and why fan-out is usually wrong
  config.md                   # the config format and the gh gotchas
skills/buildwork/scripts/
  buildwork.py                # entry point and mode dispatch
  config.py                   # read and validate .github/buildwork.toml
  gh.py                       # every gh and gh api graphql call, one place
  roadmap.py                  # parse roadmap.md, read issues and the dependency graph
  waves.py                    # effort rules, hotspot detection, wave planning
  digest.py                   # build the shared digest
  qc.py                       # the mechanical gates
  order.py                    # propose merge order
  session.py                  # the ~/.dbhq/buildwork/ session record
  state.py                    # reconstruct from git, GitHub and the runner
skills/buildwork/tests/
```

Every path `SKILL.md` names goes through `${CLAUDE_SKILL_DIR}`, never a hardcoded absolute path - wrong under a Codex install and wrong under a plugin install.

## Testing

pytest against a fake `gh` shim on `PATH` returning canned JSON, and a git fixture that builds real repositories - the same approach as `gitview`, for the same reason. A wave-planning bug does not crash, it returns a confident wrong plan and dispatches five agents on it.

The fixtures must include: two issues touching the same hotspot, a blocked-by chain, a fully chained set that must degrade to sequential, a single issue that must refuse to fan out, a worker branch with a diff outside its declared scope, and a finished branch with no pull request.

## Prior art, and what was taken

| Taken | From |
|---|---|
| Shared digest paid once and shipped to every worker | [TheColliery/CoalFace](https://github.com/TheColliery/CoalFace) |
| Mechanical QC at collection, before judgement | CoalFace |
| One bounded rework, no self-retry | CoalFace |
| Stating the honest ceiling of mechanical QC | CoalFace |
| Waves rather than a free-for-all, and a coordinator that fans out | [Augment Intent](https://www.augmentcode.com/guides/git-worktrees-parallel-ai-agent-execution) |
| A verifier as a gate against the spec | Augment Intent |
| Effort-scaling rules embedded in the prompt | [Anthropic, multi-agent research system](https://claude.com/blog/building-multi-agent-systems-when-and-how-to-use-them) |
| Keep the orchestrator thin; it classifies and delegates, it does not work | orchestrator-worker literature |
| Pull request per agent up to four or five concurrent workers | the worktree playbooks |
| Coordination state off the working tree | the same, on shared task files as a merge surface |
| The opt-in config file and `enabled = true` | `deskwork`, which took it from Joe Shirey |
| `doctor` as a drift check | `deskwork` |
| Re-verify a snapshot immediately before acting on it | `gitview` |

Rejected deliberately:

- **Read-only proposer workers with a single writer applying anchor-edits** (CoalFace). It is coherent and it is the opposite of this design. Paseo tabs are full agents in worktrees; proposing text edits would throw away the isolation the substrate already provides. Noted because if worktree coordination proves unworkable, this is the fallback position and it is already written down.
- **A dashboard or TUI** (Claude Squad, Conductor, Crystal). Paseo is the UI.
- **Merging to `base` as each worker passes.** It follows merge-early-and-often, and in `dbhq` it would deploy the site from an unreviewed agent branch.
- **An integration branch the orchestrator resolves conflicts on.** It catches semantic conflicts earlier, at the cost of the orchestrator becoming an editor. Constraint 2 is worth more.
- **Detached CLI workers.** Permission prompts have nowhere to go.

## Naming

`buildwork` keeps the `-work` suffix that `legwork` established and `deskwork` confirmed as a house pattern, per the synergy rule in `CLAUDE.md`. The namespace is clear: the exact-name repository has no stars, nothing in category, and both PyPI and npm are free.

The alternatives, and why not: `piecework` is the more precise word - it names the method rather than the output - but was passed over; `patchwork` is a 1,500-star agentic AI framework; `weft` is two AI-orchestration repositories at 2,000 and 510 stars; `signalbox` is an agent-session switcher; `outwork` is a Claude Code workspace app; `gaffer` is GCHQ's at 1,800; `allotment` is a React component at 1,200; `stint` is session-scoped change tracking for AI coding agents; `coalface` is the prior art above. `chargehand` had a genuinely empty namespace and the best meaning of any candidate, and lost only to the house suffix.

## Publishing

Per `CLAUDE.md`, a new public repo needs three places or nobody finds it:

1. GitHub metadata - description, topics, homepage.
2. [`docs/reference/github-repo-metadata.md`](../../reference/github-repo-metadata.md), in the same pass.
3. A line in `CLAUDE.md`.

Then, because it is a skill: the `marketplace` repo and `skills-site`. Standard public file set is `LICENSE`, `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `AGENTS.md`, `CODE_OF_CONDUCT.md` and `.github/dependabot.yml`, plus `.claude-plugin/plugin.json`, `install.sh` and `install-codex.sh`. Default branch `main`.

## Open items

- **`deskwork` is designed but not built.** `buildwork` does not depend on it - it reads issues and a roadmap file whoever wrote them - but the dependency graph it reads is `deskwork`'s output. Until that ships, `buildwork` treats issues as independent unless GitHub already carries blocked-by links.
- **`roadmap.md` does not exist in `dbhq` yet**, and there are three issues in the repository. The first real wave has nothing to run until `deskwork` fills the backlog, so `buildwork` will be exercised against fixtures before it is exercised against this repo.
- **The `subagent` runner's worktree isolation is host-specific.** Claude Code's Agent tool takes `isolation: "worktree"`; other hosts differ. `references/runners.md` records what each host provides and the skill says so rather than assuming.

## Settled during design

- **`dbhq-uk` has org-level Issue Types configured** - `Task`, `Bug`, `Feature`, confirmed by `gh api graphql` on 17 Sep 2026. This also closes the first open item in the `deskwork` design, which assumed them and planned a `kind:` label fallback. The fallback is still worth shipping for other orgs; it is not needed here.
