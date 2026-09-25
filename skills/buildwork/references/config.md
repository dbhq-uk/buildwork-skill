# .github/buildwork.toml

Committed to the repository it governs. Its absence is the opt-in gate.

```toml
enabled = true
runner = "auto"
roadmap = "roadmap.md"
base = "main"
gate = "python3 -m pytest -q"

hotspots = [
  "website/public/_headers",
  "docs/website/content-plan.md",
]

digest = ["CLAUDE.md", "AGENTS.md"]

[wave]
max = 4
```

`buildwork.py init` writes a starter with `enabled = false` and suggested
hotspots. Arming it is always a human's edit.

## Why TOML

The scripts are Python standard library only. The standard library parses TOML
(`tomllib`, 3.11 and later) and has never parsed YAML. A YAML config would mean
a PyPI dependency or a hand-rolled parser, and a hand-rolled parser that mostly
works is the worst of the three. `deskwork` made the same call, so the two
skills share one convention.

## The fields

### `enabled` (required)

Must be literally `true`. Not `"true"`, not `"yes"`, not absent. A
half-written or copied-in file must not arm a tool that dispatches agents at a
repository.

### `runner`

`auto`, `paseo` or `subagent`. `auto` resolves at dispatch: Paseo MCP tools
present means `paseo`, otherwise a worktree-capable subagent tool in the host,
otherwise it refuses rather than guessing.

### `roadmap`

Path to the ordered queue, relative to the repository root. Default
`roadmap.md`. It is read, never written - `deskwork` renders it.

No roadmap is not an error. The plan falls back to every open issue in no
particular order and **says so**, because presenting arbitrary order as a plan
is worse than having no plan.

### `base`

The branch pull requests target. Default `main`.

Workers are cut from `origin/<base>`, not from the local branch. `plan` runs
`git fetch origin <base>` first and stops if it cannot, and `qc` and `order`
diff against `origin/<base>`. So a wave planned after the last one merged on
GitHub starts from the merged work, whether or not anybody pulled. The fetch
moves only the remote-tracking ref; your local branch is left alone, and
`doctor` says when it has fallen behind.

### `gate`

A shell command run in the worker's worktree at collection. Usually the test
suite. Exit 0 passes.

Leaving it unset is allowed and is reported by `doctor`, because it means
nothing mechanical verifies a branch works before somebody merges it.

The gate is skipped, with a warning, if no worktree is checked out on the
branch - which happens when a Paseo workspace has already been archived. Scope
and hotspot checks still run, because those read the diff rather than the tree.

### `hotspots`

Files or directories where a parallel edit is guaranteed to conflict. Matching
is exact path or directory prefix, so `docs/site` covers `docs/site/copy.md`
and does not cover `docs/sitemap.xml`.

Two effects:

- **Planning.** Two issues touching the same hotspot never share a wave.
- **QC.** A branch that touched a hotspot it was not sent to change fails,
  even if the issue declared it.

The plan decides which issue *is* the hotspot change, and `plan --save`
records it in the session. `qc` and `order` read that record, so the branch
sent to change a hotspot passes and goes first in the merge order, and any
other branch that touches it still fails. `--allow-hotspot` gives the same
permission by hand, for `brief` and for `qc` outside a saved plan. With no
session, `order` knows of no permission and holds a hotspot branch back.

### `digest`

Files read once by the orchestrator and shipped verbatim into every worker's
prompt. Conventions, house style, invariants.

Each file is truncated at 20,000 characters, loudly. A convention document
longer than that is being used as a manual, and shipping half of it to five
workers silently is worse than saying so.

A digest file that does not exist is reported by `doctor`, because its absence
is invisible at dispatch and shows up as five workers ignoring a convention.

### `wave.max`

The ceiling on concurrent workers. **Config can only ever tighten a runner's
own cap, never raise it** - `max = 12` against the subagent runner still gets
you 2. Someone writing a larger number has misunderstood what they are asking
for, and the runner's limit is the one that means something.

## Branch naming

Not configurable, on purpose: `buildwork/issue-<N>-<slug>`.

The branch name is the join key that makes resume work. `status` reconstructs
which issue is where by reading branch names off git, so it is correct after a
crash, a reboot, or a session that died with its agent ids in it. A
configurable pattern would be one more thing that can disagree with reality.
