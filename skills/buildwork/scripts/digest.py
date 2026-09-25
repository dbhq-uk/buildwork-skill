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
    runner: str = "paseo",
    earlier: int = 0,
    gate: str | None = None,
    hotspots: tuple[str, ...] = (),
) -> str:
    """The whole of what a worker is told. It has no context but this.

    `cut_from` is the ref the worktree was made from, `origin/<base>` in use.
    `base` is the branch the pull request targets and the worker must not touch.

    Under the subagent runner the host makes the worktree, names its branch
    and picks its base, so the brief opens by putting both right. Without it
    the worker commits to a branch no later command can find, cut from a base
    the config never named.

    `gate` and `hotspots` come from the config, so the worker is shown the
    exact bar `qc` will hold it to: the command it runs, and every path it
    fails a branch for touching. A worker told only "the checks pass" and
    "leave shared files alone" guesses, and a wrong guess spends its one
    rework.

    `earlier` is the number of commits already on the branch. It is not zero
    only on a re-dispatch, and then the worker is told to build on them. A
    subagent is never told: its host always makes a new branch, the rename
    onto a name that exists fails, and the worker stops at its first step,
    which is right.
    """
    cut_from = cut_from or base
    first = _subagent_start(branch, cut_from) if runner == "subagent" else ""
    where = (
        f"- Your branch is `{branch}` once you have renamed it, cut from `{cut_from}`."
        if runner == "subagent" else
        f"- Your branch is `{branch}`, already checked out, cut from `{cut_from}`."
    )
    if earlier and runner != "subagent":
        where += (
            f"\n- An earlier worker started this issue and stopped before it opened a pull\n"
            f"  request. Its {earlier} commit(s) are already on `{branch}`. Read them with\n"
            f"  `git log {cut_from}..HEAD` before you change anything, keep what is right,\n"
            f"  and finish the issue from there. Do not start again."
        )
    scope = (
        "\n".join(f"- `{p}`" for p in declared)
        if declared else
        "- The issue does not name files. Work out the scope from the issue, keep it tight, and say what you touched."
    )

    hotspot_line = _hotspots(hotspots, allowed_hotspots)
    checks = (
        f"- The repository's own checks pass: run {_code(gate)} in your worktree before\n"
        f"  you push. `qc` runs exactly that on your branch when you finish."
        if gate else
        "- The repository's own checks pass."
    )

    return f"""\
{first}## Task

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

{where}
- Commit your work, push it with `git push -u origin {branch}`, and open a pull
  request against `{base}` whose body contains `Closes #{issue['number']}`.
- Do not merge, and do not touch `{base}`.
- Do not rebase, unless the orchestrator sends it back as your one rework
  because the branch conflicts. Then fetch, rebase this branch and only this
  branch onto `{cut_from}`, resolve the conflicts, run the checks again, and
  push it with `git push --force-with-lease`.
- Do not open issues, and do not start work the issue did not ask for. Note it in
  the pull request body instead.

## Done means

- The issue's acceptance criteria are met.
{checks}
- A pull request is open, with `Closes #{issue['number']}` in its body.

{digest_text}
"""


def _code(text: str) -> str:
    """Markdown inline code that survives a backtick inside the command."""
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def _hotspots(hotspots: tuple[str, ...], allowed: tuple[str, ...]) -> str:
    """The hotspot rules by path: the one this worker may change, and every one it may not."""
    barred = [spot for spot in hotspots if spot not in allowed]
    parts: list[str] = []
    if allowed:
        parts.append(
            f"**You are the one change permitted to touch {', '.join(_code(a) for a in allowed)} in this wave.** "
            f"Other workers are explicitly barred from it."
        )
    if barred:
        parts.append(
            "**Do not touch these paths.** They are this repository's hotspots. Other agents are "
            "working in parallel branches right now, these conflict on every one of them, and `qc` "
            "fails a branch that changes one:\n\n"
            + "\n".join(f"- {_code(spot)}" for spot in barred)
        )
        parts.append(
            "If your issue cannot be done without one, stop and say so rather than editing it. "
            "Leave any other shared file alone too."
        )
    elif not allowed:
        parts.append(
            "**Do not touch shared configuration, route registries, lockfiles or content plans.** "
            "Other agents are working in parallel branches right now and those files conflict on every one of them. "
            "If your issue cannot be done without one, stop and say so rather than editing it."
        )
    return "\n" + "\n\n".join(parts) + "\n"


def _subagent_start(branch: str, cut_from: str) -> str:
    """The first thing a host subagent does: take the buildwork branch name, and prove the base."""
    return f"""\
## Before anything else

The host made your worktree. It named the branch itself, and it may have cut
it from a different base. Put the name right and check the base before you
change a single file:

1. Rename the branch: `git branch -m {branch}`
2. Check the name: `git branch --show-current` must print `{branch}`.
3. Check the base: `git rev-parse HEAD` and `git rev-parse {cut_from}` must
   print the same commit.

If a step fails, or a check does not hold, stop. Change nothing, and report
which step it was and exactly what git printed. A branch under another name is
invisible to the checks that collect your work, and a branch cut from another
base carries somebody else's changes into your pull request.

"""
