"""Propose a merge order, with a reason attached to every position.

Reasoned, not computed, and therefore built to be reviewed rather than
believed. The order will differ between runs, so it ships with its reasoning
the same way deskwork's roadmap does.

Three rules, in priority order:

1. A pull request touching a hotspot goes first. Every other branch will have
   to rebase over it, and doing that once at the front is cheaper than each
   branch discovering it separately.
2. Then dependency order. A branch whose issue is blocked by another issue in
   this set merges after it.
3. Then smallest diff first, which shrinks everyone else's rebase.

This module proposes. It has no merge verb, which is what makes "buildwork
never merges" hold itself rather than depend on restraint.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Ready:
    issue: int
    branch: str
    pr: int | None
    hotspots: tuple[str, ...] = ()
    blocked_by: tuple[int, ...] = ()
    diff_size: int = 0
    qc_passed: bool = True


@dataclass(frozen=True)
class Position:
    item: Ready
    reason: str


def propose(items: list[Ready]) -> tuple[list[Position], list[str]]:
    """Return the ordered positions and any notes the human needs before merging."""
    notes: list[str] = []

    failed = [i for i in items if not i.qc_passed]
    if failed:
        notes.append(
            "Held back, QC not passed: "
            + ", ".join(f"#{i.issue}" for i in failed)
            + ". These are not in the order below."
        )

    ready = [i for i in items if i.qc_passed]
    no_pr = [i for i in ready if i.pr is None]
    if no_pr:
        notes.append(
            "No pull request yet: "
            + ", ".join(f"#{i.issue} ({i.branch})" for i in no_pr)
            + ". The branch exists but nothing was opened against it."
        )

    in_set = {i.issue for i in ready}
    placed: list[Position] = []
    remaining = list(ready)
    merged: set[int] = set()

    while remaining:
        available = [i for i in remaining if not (set(i.blocked_by) & in_set - merged)]
        if not available:
            # A cycle among the ready branches. Say so rather than picking one.
            notes.append(
                "Circular dependency among "
                + ", ".join(f"#{i.issue}" for i in remaining)
                + ". These are listed in roadmap order; the cycle needs resolving first."
            )
            available = remaining[:1]

        def key(item: Ready) -> tuple[int, int, int]:
            return (0 if item.hotspots else 1, item.diff_size, item.issue)

        pick = min(available, key=key)
        placed.append(Position(item=pick, reason=_reason(pick, placed, in_set, merged)))
        merged.add(pick.issue)
        remaining.remove(pick)

    return placed, notes


def _reason(item: Ready, placed: list[Position], in_set: set[int], merged: set[int]) -> str:
    deps = sorted(set(item.blocked_by) & in_set)
    if item.hotspots:
        return (
            f"touches {', '.join(item.hotspots)}, so it goes first and everything else "
            f"rebases over it once"
        )
    if deps:
        return "blocked by " + ", ".join(f"#{n}" for n in deps) + ", so it follows them"
    if not placed:
        return "nothing blocks it and no branch touches a hotspot"
    return f"independent, and the smallest remaining diff at {item.diff_size} lines"


def render(positions: list[Position], notes: list[str]) -> str:
    lines = ["Proposed merge order. buildwork does not merge - this is for you to action.", ""]
    for n, pos in enumerate(positions, 1):
        pr = f"PR #{pos.item.pr}" if pos.item.pr else f"branch {pos.item.branch}"
        lines.append(f"{n}. {pr} (closes #{pos.item.issue})")
        lines.append(f"   {pos.reason}")
    if notes:
        lines.append("")
        lines.extend(notes)
    return "\n".join(lines)
