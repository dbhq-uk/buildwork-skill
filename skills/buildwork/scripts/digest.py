"""Build the shared digest: the context every worker in a wave needs, read once.

Without this, five workers each re-read CLAUDE.md, AGENTS.md and the same four
convention files before doing anything. That duplicated reading is a large part
of why people try fan-out once and conclude it is too expensive.

The digest is shipped inside each worker's initial prompt. It is not a summary
written by a model - it is the files themselves, so nothing is lost in the
retelling and nothing is invented.
"""

from __future__ import annotations

from pathlib import Path

# Per file. A convention document longer than this is being used as a manual,
# and truncating loudly beats silently shipping half of it to every worker.
MAX_CHARS = 20_000


def collect(root: Path, paths: tuple[str, ...]) -> tuple[str, list[str]]:
    """Return the digest text and a list of anything that could not be read."""
    parts: list[str] = []
    problems: list[str] = []

    for rel in paths:
        path = root / rel
        if not path.is_file():
            problems.append(f"{rel}: not found")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"{rel}: {exc}")
            continue
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + f"\n\n[truncated at {MAX_CHARS} characters - read {rel} in full if you need the rest]"
            problems.append(f"{rel}: truncated at {MAX_CHARS} characters")
        parts.append(f"### {rel}\n\n{text.strip()}")

    if not parts:
        return "", problems

    header = (
        "## Shared context\n\n"
        "These files were read once and shipped to you so you do not have to read them "
        "again. They are the repository's conventions and they bind your work.\n"
    )
    return header + "\n\n".join(parts), problems


def brief(
    issue: dict,
    base: str,
    branch: str,
    digest_text: str,
    declared: tuple[str, ...],
    allowed_hotspots: tuple[str, ...] = (),
    cut_from: str | None = None,
) -> str:
    """The whole of what a worker is told. It has no context but this.

    `cut_from` is the ref the worktree was made from, `origin/<base>` in use.
    `base` is the branch the pull request targets and the worker must not touch.
    """
    scope = (
        "\n".join(f"- `{p}`" for p in declared)
        if declared else
        "- The issue does not name files. Work out the scope from the issue, keep it tight, and say what you touched."
    )

    hotspot_line = (
        f"\n**You are the one change permitted to touch {', '.join(allowed_hotspots)} in this wave.** "
        f"Other workers are explicitly barred from it.\n"
        if allowed_hotspots else
        "\n**Do not touch shared configuration, route registries, lockfiles or content plans.** "
        "Other agents are working in parallel branches right now and those files conflict on every one of them. "
        "If your issue cannot be done without one, stop and say so rather than editing it.\n"
    )

    return f"""\
## Task

{issue.get('title', '')}

Implement issue #{issue['number']} and open a pull request. Nothing else.

## The issue

{(issue.get('body') or '').strip()}

## Scope

{scope}
{hotspot_line}
## How this is being run

You are one of several agents working in parallel, each on a separate issue in
its own worktree on its own branch. You cannot see the others and must not try
to. Anything you need that is not here, read from the repository.

- Your branch is `{branch}`, already checked out, cut from `{cut_from or base}`.
- Commit your work, push the branch, and open a pull request whose body contains
  `Closes #{issue['number']}`.
- Do not merge. Do not rebase onto anything. Do not touch `{base}`.
- Do not open issues, and do not start work the issue did not ask for. Note it in
  the pull request body instead.

## Done means

- The issue's acceptance criteria are met.
- The repository's own checks pass.
- A pull request is open, with `Closes #{issue['number']}` in its body.

{digest_text}
"""
