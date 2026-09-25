# AGENTS.md

Guidance for AI agents (and people) working in this repository.

## What this is

**buildwork** - an agent skill that runs a repository's open issues as parallel
agents, one per issue, each in its own worktree and its own pull request, then
checks them and proposes a merge order. It follows the
[Agent Skills](https://agentskills.io) layout (`skills/<name>/SKILL.md`) and
ships as a [Claude Code plugin](https://code.claude.com/docs/en/plugins).

It is the execution half of a pair. [`deskwork`](https://github.com/dbhq-uk/deskwork-skill)
decides what the work is and what order it goes in; buildwork runs it.

## Layout

```
.claude-plugin/plugin.json          # plugin manifest
skills/buildwork/SKILL.md           # the skill (agent-facing instructions)
skills/buildwork/references/        # runners, waves, config - read on demand
skills/buildwork/scripts/           # Python, standard library only
skills/buildwork/tests/             # pytest, no network, no token, no agent
install.sh / install-codex.sh       # local symlink installers
docs/superpowers/specs/             # the dated design record
```

## The constraints that must not be broken

Everything else here is a preference. These are not.

**1. There is no merge verb, and there must never be one.** No `gh pr merge`,
no push to the base branch, and the orchestrator never rebases a worker's
branch. A worker may rebase its own branch onto `origin/<base>`, as its one
rework, when `order` finds a conflict. `order.py` proposes and renders; it
cannot act. The conflict check uses `git merge-tree --write-tree` and
`git commit-tree`, which write objects and move no ref, index or worktree. In
a repository where merging to the default branch is the deploy - which is true
of the repository this was written for - that absence is the only thing
standing between an agent and production. Do not add a "just merge the clean
ones" convenience.

**2. The orchestrator never edits code.** Every edit happens in a worker's
worktree on a worker's branch. A thin orchestrator that classifies, delegates
and collects is the whole design; one that also edits is the monolith one level
up, and it arrives one helpful commit at a time.

**3. The refusal is a feature, not a fallback.** `waves.plan()` returning a
refusal is a correct, valuable result. A single agent matches or beats a
multi-agent system on most tasks at a fifteenth of the tokens, so the commonest
mistake this tool can prevent is using it. Never weaken a refusal into a
warning, and never add a `--force` that skips them.

**4. No config, or no `enabled = true`, means no action.** Not a warning, not a
prompt, not a default. `config.load()` raises and the caller stops. `init`
always writes `enabled = false`.

**5. QC's ceiling is stated, never implied away.** Mechanical checks catch
scope violations, hotspot violations and a failing gate. A semantically wrong
change with no covering test passes all three. `Report.summary()` says "a
floor, not a verdict" on every pass and that wording earns its place - a tool
that reports a green tick without it will be read as having approved the
change.

**6. One rework per failure, then a human.** Never two, never a loop. An agent
that retries itself spends without bound.

**7. Resume is reconstructed, never cached.** State comes from git branches,
pull requests in every state and worktrees, plus the runner's list of working
agents when the orchestrator passes it to `status --live`. That list is read
at the time of asking and never written down. The session record in `~/.dbhq/buildwork/`
holds the goal, the wave and which issue was sent to change which hotspot, and
nothing a query could answer. It is keyed on the `owner/repo` gh names, never
on a folder, so every worktree of a repository finds the same one. A branch is
found by its issue number, never by rebuilding its name from a title that may
have changed. If you find
yourself caching an agent id to make something faster, you have made it wrong
after the next crash.

**8. Standard library only, and no credential.** Python stdlib plus `git` and
`gh`. `gh auth` is the credential; there is nothing in this repository or in
`~/.dbhq/buildwork/` to leak. This is why the config is TOML - `tomllib` is in
the stdlib and no YAML parser is.

## Conventions

- Any path `SKILL.md` names goes through `${CLAUDE_SKILL_DIR}`, which Claude
  Code substitutes for personal, project and plugin installs alike. **Never
  hardcode `~/.claude/skills/buildwork` or any absolute path** - it is wrong
  under a Codex install and wrong under a plugin install. `install-codex.sh`
  rewrites the variable at install time because Codex does not substitute it.
  **Always braced.** Claude Code substitutes `${CLAUDE_SKILL_DIR}` and leaves
  `$CLAUDE_SKILL_DIR` to the shell, where it is unset, so the unbraced form
  runs `/scripts/buildwork.py`. CI fails on it, and `test_skill_md.py` runs
  the `doctor` command as the host would.
- `SKILL.md` is the short half on purpose. Workflow, rules and commands live
  there; reasoning lives in `references/` and is read on demand.
- The branch pattern `buildwork/issue-<N>-<slug>` is not configurable. It is
  the join key that makes resume work without a cache.
- House style: British English, plain hyphens, **no em dashes** - CI fails on
  them. No trailing full stops on headings.
- Every example is generic: `owner/repo`, `#143`, `src/routes.ts`. CI greps for
  anything resembling a real ticket id, hostname, IP address or organisation.

## Where the logic lives

The split is deliberate and worth preserving:

- **Python does the deterministic half** - config, roadmap parsing, hotspot
  detection, wave planning, briefs, QC gates, merge ordering. All of it is
  tested without a network, a token or an agent.
- **`SKILL.md` does dispatch and judgement**, because dispatch goes through MCP
  tools or a host's subagent surface and a subprocess can call neither.

A change that needs runner knowledge inside `waves.py`, `qc.py` or `order.py`
means the boundary has moved to the wrong place. Those three are
runner-independent and every runner benefits from keeping them that way.

## Validating a change

```bash
bash -n install.sh install-codex.sh
jq empty .claude-plugin/plugin.json
python3 -m pytest skills/buildwork/tests -q
```

CI runs those plus the two prose checks.

The tests are worth more than they look. A wave-planning bug does not crash -
it returns a confident wrong plan and dispatches agents on it. So the fixtures
deliberately include the cases that produce plausible wrong answers: two issues
on one hotspot, a fully chained set that must degrade to sequential, a single
issue that must refuse, a `blocked by #143` line in prose that must not be read
as a queue entry, a cross-repo `owner/repo#26` that must never become local
issue 26 (in the roadmap or in GitHub's dependency links), a bare `after #12`
in prose that must not become an edge, a 31st blocker on a second page, one
issue listed under both Next and Triage that must be held, and an open blocker
outside the selection that must hold its issue.

`test_roadmap.py` keeps deskwork's output shapes as fixtures, old and new. The
contract is only the `## Next`, `## Blocked`, `## Later` and `## Triage`
headings and entries like `1. **#12** Title`. Do not make the parser depend on
anything newer that deskwork writes.

### The CLI harness

The pure modules are tested as functions. Everything that meets git and GitHub
is tested end to end in `test_cli.py`, through the harness in
`tests/harness.py`:

- **Real git.** A working clone of a bare remote, with real branches, linked
  worktrees and squash merges. Nothing about git is mocked.
- **A fake `gh`** (`tests/fake_gh.py`) first on PATH, answering from state the
  test sets. It fails the way gh 2.100 fails: a non-zero exit with gh's own
  stderr, a 404 body on stdout, one REST page of 30 without `--paginate`, and
  `--state closed` including merged pull requests. A command it does not model
  exits 1 with `fake gh: unsupported`. If a fix trips that, teach the fake what
  GitHub really prints; do not make it answer something convenient.
- **`buildwork.py` as a subprocess**, the way SKILL.md runs it, with a private
  `HOME` so no session record reaches the real `~/.dbhq/buildwork/`.

A test marked `@bug(N)` reproduces open issue #N. It is a strict xfail, so it
fails today and fails the suite again the day the bug is fixed. The fix removes
the marker in the same pull request. That is how every fix here arrives with a
test that failed on the commit before it.
