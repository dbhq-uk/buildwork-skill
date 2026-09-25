"""The session record: the goal, the wave it produced, and who may touch which hotspot.

This is the only thing buildwork writes outside the repository, and it holds
only what cannot be reconstructed. Which tab is on which issue, which branch
exists, what has a pull request - all of that is read back from git, GitHub and
the runner, so it is always current and always survives a crash.

The session goal cannot be. Nobody can recover "we were trying to get the
website deploy unblocked today" from a list of branches, and without it a
resumed session cannot tell whether a half-finished wave is still the right
thing to be doing.

Nor can the hotspot permissions. The approved plan sent one issue to change
each hotspot, and `qc` and `order` must hold every other branch to that. Read
back from the issue bodies instead, an edit after dispatch could permit a
second branch to touch the same file.

Lives in ~/.dbhq/buildwork/, per the DBHQ convention that every skill keeps its
state in ~/.dbhq/<skill>/ - never a new dotfile in $HOME, never in the working
tree, where it would appear in every worktree at once.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

STATE_DIR = Path.home() / ".dbhq" / "buildwork"

# A session older than this is reported as stale rather than resumed silently.
# Waves finish in hours; a record from last week describes a different problem.
STALE_AFTER = 3 * 24 * 60 * 60


@dataclass
class Session:
    repo: str
    goal: str
    issues: list[int] = field(default_factory=list)
    waves: list[list[int]] = field(default_factory=list)
    runner: str = "auto"
    started: float = field(default_factory=time.time)
    # Issue number (as a string, because JSON keys are) to the hotspots the
    # plan sent that issue to change.
    hotspots: dict[str, list[str]] = field(default_factory=dict)

    def allowed_hotspots(self, issue: int) -> tuple[str, ...]:
        """The hotspots this issue was sent to change. Empty for every other issue."""
        return tuple(self.hotspots.get(str(issue), ()))

    @property
    def age(self) -> float:
        return time.time() - self.started

    @property
    def stale(self) -> bool:
        return self.age > STALE_AFTER

    def age_text(self) -> str:
        hours = self.age / 3600
        if hours < 1:
            return f"{int(self.age / 60)} minutes ago"
        if hours < 48:
            return f"{int(hours)} hours ago"
        return f"{int(hours / 24)} days ago"


def _slug(repo_root: Path) -> str:
    return repo_root.name


def _path(repo_root: Path) -> Path:
    return STATE_DIR / f"{_slug(repo_root)}.json"


def _ensure_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)


def save(repo_root: Path, session: Session) -> Path:
    _ensure_dir()
    path = _path(repo_root)
    path.write_text(json.dumps(asdict(session), indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def load(repo_root: Path) -> Session | None:
    path = _path(repo_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # A corrupt record is not worth an error. Everything it held except the
        # goal can be reconstructed, and the goal can be asked for again.
        return None
    known = {f for f in Session.__dataclass_fields__}
    return Session(**{k: v for k, v in data.items() if k in known})


def clear(repo_root: Path) -> None:
    _path(repo_root).unlink(missing_ok=True)
