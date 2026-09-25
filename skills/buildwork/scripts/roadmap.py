"""Parse roadmap.md into an ordered, sectioned list of issue numbers.

The roadmap is deskwork's output and buildwork only ever reads it. The format
is deliberately loose - it is a document a human reviews, not a data file - so
this parser is strict about one thing only: what counts as an entry.

An entry is the first issue reference in a list item. Every other `#N` on the
line is reasoning ("blocked by #143", "reasoned ahead of #147") and picking
those up would silently double the queue. So is a `Why:` line under an entry:
it is indented prose, never a list item.

The contract with deskwork is only this: `## Next`, `## Blocked`, `## Later`
and `## Triage` headings, and entries shaped like `1. **#12** Title`. Anything
else deskwork writes is read by the same rules, and nothing here depends on a
newer deskwork than that.

One issue can be listed in more than one section. A held listing always wins,
whichever comes first: an issue under both Next and Triage has not been
reviewed, and running it because Next happened to come first would dispatch
an agent at work nobody approved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# A list item: "1. **#143** title", "- #36 title", "* **#12**".
ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*)$")

# The first issue reference in an item. A cross-repo reference (owner/repo#26)
# is matched so it can be skipped rather than mistaken for a local issue - the
# number after the hash means nothing without its repo.
REF = re.compile(r"(?P<repo>[\w.-]+/[\w.-]+)?#(?P<num>\d+)")

RUNNABLE_SECTIONS = ("next", "now", "in progress", "ready")
HELD_SECTIONS = ("blocked", "triage", "waiting", "later", "icebox", "done", "cycles")

# Sections that mention issues listed elsewhere, to describe them rather than
# to place them. deskwork's Bottlenecks names the issues that most need to go
# first, so a mention there must not hold an issue that Next runs.
NOTE_SECTIONS = ("bottlenecks",)

RUN, HOLD, NOTE = "run", "hold", "note"


@dataclass(frozen=True)
class Entry:
    number: int
    section: str
    title: str
    runnable: bool


@dataclass(frozen=True)
class Roadmap:
    entries: tuple[Entry, ...]
    source: str          # "roadmap.md" or "issues" when there was no file
    note: str = ""       # what the caller must tell the human about how this was read
    warnings: tuple[str, ...] = ()  # issues held because a held section also lists them

    @property
    def runnable(self) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if e.runnable)

    def numbers(self) -> list[int]:
        return [e.number for e in self.entries]


def _classify(heading: str) -> tuple[str, str]:
    name = heading.strip().lower().lstrip("#").strip()
    # "Triage", or the older "Triage - not yet in the roadmap": match on the
    # leading word.
    for token in RUNNABLE_SECTIONS:
        if name.startswith(token):
            return name, RUN
    for token in NOTE_SECTIONS:
        if name.startswith(token):
            return name, NOTE
    for token in HELD_SECTIONS:
        if name.startswith(token):
            return name, HOLD
    # An unrecognised heading is held, not run, and a listing under it holds
    # an issue that Next also lists. A roadmap someone restructured must not
    # start dispatching agents from a section this parser has never seen.
    return name, HOLD


def parse(text: str) -> Roadmap:
    # Every listing, in document order: (number, section, kind, title).
    listings: list[tuple[int, str, str, str]] = []
    section, kind = "", HOLD

    for line in text.splitlines():
        if line.startswith("## "):
            section, kind = _classify(line[3:])
            continue
        match = ITEM.match(line)
        if not match or not section:
            continue

        rest = match.group(1)
        ref = REF.search(rest)
        if not ref or ref.group("repo"):
            # No reference, or the first one is cross-repo. Either way there is
            # no local issue here to run.
            continue

        title = rest[ref.end():].strip().lstrip("*").strip()
        title = re.sub(r"^[-:\u2013]\s*", "", title).strip()
        listings.append((int(ref.group("num")), section, kind, title))

    entries: list[Entry] = []
    warnings: list[str] = []
    seen: set[int] = set()
    for number, section, kind, title in listings:
        if number in seen:
            continue
        seen.add(number)
        mine = [(sec, k) for n, sec, k, _ in listings if n == number]
        runs = [sec for sec, k in mine if k == RUN]
        holds = [sec for sec, k in mine if k == HOLD]
        if runs and holds:
            warnings.append(
                f"#{number} is listed under {_heading(runs[0])} and under {_heading(holds[0])}. "
                f"A held listing wins, so it is held."
            )
        entries.append(Entry(
            number=number,
            section=holds[0] if runs and holds else section,
            title=title,
            runnable=bool(runs) and not holds,
        ))

    return Roadmap(entries=tuple(entries), source="roadmap.md", warnings=tuple(warnings))


def _heading(section: str) -> str:
    """`triage - not yet in the roadmap` back to `Triage`, for a message."""
    return re.split(r"\s+[-:\u2013]\s+", section, maxsplit=1)[0].capitalize()


def load(path: Path, fallback_issues: list[dict] | None = None) -> Roadmap:
    """Read the roadmap, or fall back to open issues with the fallback stated.

    Falling back is not an error - most repositories have no roadmap - but it
    does mean the order is unknown, and a caller that does not say so out loud
    is presenting arbitrary order as a plan.
    """
    if path.is_file():
        roadmap = parse(path.read_text(encoding="utf-8"))
        if roadmap.entries:
            return roadmap
        return Roadmap(
            entries=(), source="roadmap.md",
            note=f"{path.name} exists but has no issue entries under a recognised heading.",
            warnings=roadmap.warnings,
        )

    issues = fallback_issues or []
    entries = tuple(
        Entry(number=int(i["number"]), section="open", title=i.get("title", ""), runnable=True)
        for i in issues
    )
    return Roadmap(
        entries=entries, source="issues",
        note=(
            f"No {path.name}, so this is every open issue in no particular order. "
            f"Priority is a guess until something writes a roadmap."
        ),
    )
