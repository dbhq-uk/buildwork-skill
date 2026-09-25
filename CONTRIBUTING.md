# Contributing

Issues and pull requests are welcome. This is a small, opinionated tool, so the
most useful thing you can do before a large change is open an issue and say
what you are trying to make it do.

## Run the checks

```bash
bash -n install.sh install-codex.sh
jq empty .claude-plugin/plugin.json
python3 -m pytest skills/buildwork/tests -q
```

CI runs those plus two prose checks: no em dashes, and nothing that looks like
a real ticket id, hostname, IP address or organisation.

Needs Python 3.11 or later, for `tomllib`. No packages to install.

## Read AGENTS.md first

[`AGENTS.md`](AGENTS.md) lists eight constraints that are not preferences. The
short version, because they are the changes most likely to be proposed in good
faith and declined:

- **No merge verb.** Not even for "obviously clean" pull requests. In a
  repository where merging deploys, that absence is the whole safety story.
- **No `--force` past a refusal.** `plan` refusing to fan out is a correct
  result. A single agent beats a multi-agent system on most tasks at a
  fifteenth of the tokens, so the commonest mistake this tool can prevent is
  using it.
- **No caching of agent ids.** Resume is reconstructed from git and GitHub so
  it survives a crash. A cache makes it faster and wrong.
- **No PyPI dependency.** Standard library only. This is why the config is TOML.

If you think one of those is wrong, that is a conversation worth having in an
issue. It is not a pull request.

## Where a change belongs

- **Runner-independent logic** - planning, hotspots, QC, ordering - goes in
  `scripts/` with tests. If it needs to know which runner is in use, the
  boundary has moved to the wrong place.
- **Dispatch and judgement** go in `SKILL.md` and `references/runners.md`,
  because dispatch goes through MCP tools or a host's subagent surface and a
  Python subprocess can call neither.
- **Reasoning** goes in `references/`, not `SKILL.md`. That file is the short
  half on purpose.

## Tests

A wave-planning bug does not crash. It returns a confident wrong plan and
dispatches agents on it. So a change to `waves.py`, `qc.py` or `order.py` needs
a test that would have failed before it.

Prefer a case that produces a *plausible* wrong answer over one that produces
an obvious error - those are the ones that reach production.

A change to `gh.py`, `buildwork.py` or `session.py` needs a test in the CLI
harness: a real git repository and a fake `gh` on PATH. `test_cli.py` shows the
pattern, and AGENTS.md says how the harness works. A test marked `@bug(N)` is
an open issue; if your change makes it pass, remove the marker.

## Style

British English, plain hyphens, no em dashes, no trailing full stops on
headings. Comments explain why, not what.
