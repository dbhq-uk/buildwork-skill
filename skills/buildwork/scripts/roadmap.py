"""Parse roadmap.md into an ordered, sectioned list of issue numbers.

The roadmap is deskwork's output and buildwork only ever reads it. The format
is deliberately loose - it is a document a human reviews, not a data file - so
this parser is strict about one thing only: what counts as an entry.

An entry is the first issue reference in a list item. Every other `#N` on the
line is reasoning ("blocked by #143", "reasoned ahead of #147") and picking
those up would silently double the queue.
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
HELD_SECTIONS = ("blocked", "triage", "waiting", "later", "icebox", "done")


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

    @property
    def runnable(self) -> tuple[Entry, ...]:
        return tuple(e for e in self.entries if e.runnable)

    def numbers(self) -> list[int]:
        return [e.number for e in self.entries]


def _classify(heading: str) -> tuple[str, bool]:
    name = heading.strip().lower().lstrip("#").strip()
    # "Triage - not yet in the roadmap" and similar: match on the leading word.
    for token in RUNNABLE_SECTIONS:
        if name.startswith(token):
            return name, True
    for token in HELD_SECTIONS:
        if name.startswith(token):
            return name, False
    # An unrecognised heading is held, not run. A roadmap someone restructured
    # must not start dispatching agents from a section this parser has never
    # seen; the caller reports the unknown section instead.
    return name, False


def parse(text: str) -> Roadmap:
    entries: list[Entry] = []
    section, runnable = "", False
    seen: set[int] = set()

    for line in text.splitlines():
        if line.startswith("## "):
            section, runnable = _classify(line[3:])
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

        number = int(ref.group("num"))
        if number in seen:
            continue
        seen.add(number)

        title = rest[ref.end():].strip().lstrip("*").strip()
        title = re.sub(r"^[-:–]\s*", "", title).strip()
        entries.append(Entry(number=number, section=section, title=title, runnable=runnable))

    return Roadmap(entries=tuple(entries), source="roadmap.md")


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
