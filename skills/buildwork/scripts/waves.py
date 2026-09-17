"""Wave planning: what may safely run at once, and when nothing should.

The default failure of every tool in this category is fanning work out that one
agent should simply do. A single agent matches or beats a multi-agent system on
most tasks given the same tools and context, and a fan-out burns many times the
tokens. So the first thing this module can return is a refusal, and that is a
result rather than an error.

Two things can force work apart:

- a `blocked_by` edge, which is a real ordering constraint
- a shared hotspot file, where a parallel edit is guaranteed to conflict

Everything else is allowed to run together, and semantic conflict between
independent branches is not claimed to be solved here. See qc.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Anything backticked that could be a path.
TOKEN_IN_TICKS = re.compile(r"`([A-Za-z0-9_./-]+)`")

# Unambiguous on its own: it has a separator or a file extension, so it cannot
# be a command or a branch name.
LOOKS_LIKE_PATH = re.compile(r"^[A-Za-z0-9_./-]+(?:/[A-Za-z0-9_./-]+|\.[A-Za-z0-9]{1,6})$")


@dataclass(frozen=True)
class Candidate:
    number: int
    title: str
    files: tuple[str, ...] = ()
    hotspots: tuple[str, ...] = ()


@dataclass
class Plan:
    waves: list[list[int]] = field(default_factory=list)
    refusal: str | None = None
    warnings: list[str] = field(default_factory=list)
    cycles: list[list[int]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    @property
    def dispatched(self) -> list[int]:
        return [n for wave in self.waves for n in wave]

    @property
    def parallel(self) -> bool:
        return any(len(wave) > 1 for wave in self.waves)


def declared_files(body: str, root: Path | None = None) -> tuple[str, ...]:
    """Paths an issue body names in backticks.

    A token with a separator or an extension (`src/routes.ts`, `_headers.txt`)
    is taken as a path outright. A bare word is ambiguous - "only touch `src`"
    names a directory, but `gh`, `main` and `true` are not files - so it counts
    only when `root` is given and the path actually exists in the repository.

    Without `root`, bare words are dropped. That is the safe direction: a
    missed path makes an issue look unknown-scope, which is cautious, whereas a
    false path would exclude an unrelated issue from a wave for no reason.

    Best effort either way, and treated as such everywhere downstream. An issue
    that names no files is not assumed to touch nothing - it is assumed to be
    unknown, which is why two unknown-scope issues never share a wave.
    """
    found: list[str] = []
    for token in TOKEN_IN_TICKS.findall(body or ""):
        if LOOKS_LIKE_PATH.match(token):
            found.append(token)
        elif root is not None and (root / token).exists():
            found.append(token)
    return tuple(dict.fromkeys(found))


def hotspots_touched(files: tuple[str, ...], hotspots: tuple[str, ...]) -> tuple[str, ...]:
    """Which configured hotspots these files hit, by exact path or directory prefix."""
    hit = []
    for spot in hotspots:
        norm = spot.rstrip("/")
        for path in files:
            if path == norm or path.startswith(norm + "/"):
                hit.append(spot)
                break
    return tuple(hit)


def build_candidates(
    issues: list[dict], hotspots: tuple[str, ...], root: Path | None = None,
) -> list[Candidate]:
    out = []
    for issue in issues:
        files = declared_files(issue.get("body") or "", root)
        out.append(Candidate(
            number=int(issue["number"]),
            title=issue.get("title", ""),
            files=files,
            hotspots=hotspots_touched(files, hotspots),
        ))
    return out


def _find_cycles(graph: dict[int, list[int]], nodes: set[int]) -> list[list[int]]:
    """Every cycle reachable in the dependency graph, reported rather than smoothed over."""
    cycles, colour, stack = [], {}, []

    def walk(node: int) -> None:
        colour[node] = 1
        stack.append(node)
        for dep in graph.get(node, []):
            if dep not in nodes:
                continue
            if colour.get(dep) == 1:
                cycles.append(stack[stack.index(dep):] + [dep])
            elif colour.get(dep, 0) == 0:
                walk(dep)
        stack.pop()
        colour[node] = 2

    for node in sorted(nodes):
        if colour.get(node, 0) == 0:
            walk(node)
    return cycles


def plan(
    candidates: list[Candidate],
    graph: dict[int, list[int]],
    cap: int,
    graph_is_known: bool = True,
) -> Plan:
    """Group candidates into waves, or refuse.

    `graph` maps an issue number to the issue numbers blocking it. Edges to
    issues outside `candidates` are ignored: a blocker that is already closed,
    or that is not in this session's goal, does not constrain this wave.
    """
    result = Plan()
    nodes = {c.number for c in candidates}
    by_number = {c.number: c for c in candidates}
    order = [c.number for c in candidates]  # roadmap order, preserved throughout

    if not candidates:
        result.refusal = "Nothing to run: no open issues matched the session goal."
        return result

    if len(candidates) == 1:
        only = candidates[0]
        result.refusal = (
            f"One issue (#{only.number}). Fanning out costs a worktree, a full context "
            f"and several times the tokens to run one agent. Do it in this session."
        )
        return result

    result.cycles = _find_cycles(graph, nodes)
    if result.cycles:
        shown = ", ".join(" -> ".join(f"#{n}" for n in cycle) for cycle in result.cycles)
        result.refusal = (
            f"The dependency graph has a cycle: {shown}. Nothing can be ordered until "
            f"that is resolved, and guessing an order would dispatch work into a "
            f"dependency it was told to wait for."
        )
        return result

    # Every candidate declaring the *same* set of files is one piece of work
    # wearing several issue numbers, and no ordering saves it. Sharing some
    # files is different and is handled by serialising the wave below.
    with_files = [c for c in candidates if c.files]
    if len(with_files) == len(candidates) >= 2:
        first = set(candidates[0].files)
        if all(set(c.files) == first for c in candidates[1:]):
            names = ", ".join(sorted(first)[:3])
            result.refusal = (
                f"All {len(candidates)} issues declare exactly the same files ({names}). "
                f"That is one piece of work wearing {len(candidates)} issue numbers, and "
                f"parallel branches would conflict on every line. Do these in sequence, "
                f"in this session."
            )
            return result

    if not graph_is_known:
        result.assumptions.append(
            "No dependency links were readable, so these issues are treated as "
            "independent. If one actually blocks another, this plan runs them together."
        )

    unknown_scope = [c.number for c in candidates if not c.files]
    if len(unknown_scope) > 1:
        result.warnings.append(
            "Issues " + ", ".join(f"#{n}" for n in unknown_scope) + " declare no file paths, "
            "so their scope is unknown and no overlap check was possible for them."
        )

    # --- levelled topological sort, roadmap order preserved within a level ---
    remaining = set(nodes)
    blocked = {n: [d for d in graph.get(n, []) if d in nodes] for n in nodes}
    waves: list[list[int]] = []

    while remaining:
        ready = [n for n in order if n in remaining and not (set(blocked[n]) & remaining)]
        if not ready:
            # Unreachable: cycles were rejected above. Kept as a hard stop rather
            # than an infinite loop if that ever stops being true.
            result.refusal = "The dependency graph could not be ordered."
            return result

        wave: list[int] = []
        claimed: set[str] = set()
        for number in ready:
            cand = by_number[number]
            # Two branches editing one file conflict whether or not anybody
            # listed it as a hotspot. The hotspot list exists because those
            # files conflict even when no issue admits to touching them.
            wants = set(cand.files) | set(cand.hotspots)
            clash = claimed & wants
            if clash:
                result.warnings.append(
                    f"#{number} waits a wave: it touches {', '.join(sorted(clash))}, "
                    f"already claimed in this wave."
                )
                continue
            if not cand.files and any(not by_number[m].files for m in wave):
                # Two unknown-scope issues in one wave is an unbounded bet.
                continue
            wave.append(number)
            claimed |= wants
            if len(wave) >= cap:
                break

        if not wave:
            # Everything ready is held by a hotspot claim from this pass. Take
            # the first one alone so the loop always advances.
            wave = [ready[0]]

        waves.append(wave)
        remaining -= set(wave)

    result.waves = waves

    if not result.parallel and len(waves) > 1:
        result.assumptions.append(
            f"Fully sequential: {len(waves)} waves of one. The dependency chain admits "
            f"no parallelism, so this is not faster than doing it yourself - it is only "
            f"separated. Consider running it in this session instead."
        )

    return result
