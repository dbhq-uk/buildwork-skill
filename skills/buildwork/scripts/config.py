"""Read and validate .github/buildwork.toml.

The config file is the opt-in gate. No file, or no `enabled = true` inside it,
means the skill does nothing at all - not a warning, not a prompt. A
half-written or copied-in file must not arm a tool that dispatches agents.

TOML rather than YAML because the standard library parses TOML and has never
parsed YAML. A YAML config would mean a PyPI dependency or a hand-rolled
parser, and a hand-rolled parser that mostly works is worse than either.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = ".github/buildwork.toml"

RUNNERS = ("auto", "paseo", "subagent")

# Per-runner wave caps. Paseo tabs are supervised and survive the session, so
# four is readable. Host subagents die with the session and send every
# permission prompt to it, so two is as far as trust reaches.
RUNNER_WAVE_CAP = {"paseo": 4, "subagent": 2}


class ConfigError(Exception):
    """The config is absent, unparseable, or refuses to arm the skill."""


@dataclass(frozen=True)
class Config:
    root: Path
    runner: str = "auto"
    roadmap: str = "roadmap.md"
    base: str = "main"
    gate: str | None = None
    hotspots: tuple[str, ...] = ()
    digest: tuple[str, ...] = ()
    wave_max: int = 4
    hold_labels: tuple[str, ...] = ()

    @property
    def roadmap_path(self) -> Path:
        return self.root / self.roadmap

    def cap_for(self, runner: str) -> int:
        """The effective wave cap: the config's number or the runner's, whichever is lower.

        Config can only ever tighten a runner's ceiling. Someone writing
        `max = 12` against the subagent runner has misunderstood what they are
        asking for, and the runner's own limit is the one that means something.
        """
        return min(self.wave_max, RUNNER_WAVE_CAP.get(runner, self.wave_max))


def _require(value: object, kind: type, name: str) -> object:
    if not isinstance(value, kind):
        raise ConfigError(f"{CONFIG_PATH}: `{name}` must be {kind.__name__}, got {type(value).__name__}")
    return value


def _str_list(raw: object, name: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    _require(raw, list, name)
    for item in raw:
        _require(item, str, f"{name}[]")
    return tuple(raw)


def load(root: Path) -> Config:
    """Load the config for the repository at `root`, or raise ConfigError.

    Every failure here is deliberately fatal rather than defaulted. The caller
    is about to dispatch agents at a repository; guessing what the human meant
    is not an acceptable way to decide how many.
    """
    path = root / CONFIG_PATH
    if not path.is_file():
        raise ConfigError(
            f"No {CONFIG_PATH} in {root}. buildwork is opt-in per repository; "
            f"run `buildwork.py init` to write a starter config."
        )

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{CONFIG_PATH} is not valid TOML: {exc}") from exc

    if data.get("enabled") is not True:
        raise ConfigError(
            f"{CONFIG_PATH} does not say `enabled = true`. buildwork does nothing "
            f"until it does. This is the gate, not an oversight."
        )

    runner = data.get("runner", "auto")
    _require(runner, str, "runner")
    if runner not in RUNNERS:
        raise ConfigError(f"{CONFIG_PATH}: `runner` must be one of {', '.join(RUNNERS)}, got {runner!r}")

    wave = data.get("wave") or {}
    _require(wave, dict, "wave")
    wave_max = wave.get("max", 4)
    _require(wave_max, int, "wave.max")
    if wave_max < 1:
        raise ConfigError(f"{CONFIG_PATH}: `wave.max` must be at least 1, got {wave_max}")

    gate = data.get("gate")
    if gate is not None:
        _require(gate, str, "gate")

    return Config(
        root=root,
        runner=runner,
        roadmap=str(_require(data.get("roadmap", "roadmap.md"), str, "roadmap")),
        base=str(_require(data.get("base", "main"), str, "base")),
        gate=gate,
        hotspots=_str_list(data.get("hotspots"), "hotspots"),
        digest=_str_list(data.get("digest"), "digest"),
        wave_max=wave_max,
        hold_labels=_str_list(data.get("hold_labels"), "hold_labels"),
    )


STARTER = """\
# buildwork - https://github.com/dbhq-uk/buildwork-skill
#
# Nothing happens until enabled = true. That is the gate, not a formality:
# this file arms a tool that dispatches agents at your repository.
enabled = false

# auto | paseo | subagent
runner = "auto"

roadmap = "roadmap.md"
base = "{base}"

# Run in each worker's worktree at collection. A branch that fails it is not
# offered for merge. Leave unset to skip the mechanical gate entirely, which
# means judgement is the only check there is.
# gate = "python3 -m pytest -q"

# Files where a parallel edit is guaranteed to conflict. Two issues in a wave
# touching one of these means the hotspot change lands alone, on base, first.
# `buildwork.py init` suggests these from the files most often touched in
# recent merges - check them, they are a starting point rather than an answer.
hotspots = [
{hotspots}]

# Read once by the orchestrator and shipped into every worker's prompt, so
# five agents do not each re-read the same conventions.
digest = [
{digest}]

# An issue with any of these labels is never dispatched, whatever the roadmap
# or --issues says.
# hold_labels = ["blocked"]

[wave]
max = {cap}
"""


def starter(base: str = "main", hotspots: list[str] | None = None, digest: list[str] | None = None) -> str:
    """Render a starter config. Always `enabled = false`; arming it is the human's move."""
    def block(items: list[str] | None) -> str:
        return "".join(f'  "{item}",\n' for item in (items or []))

    return STARTER.format(
        base=base,
        hotspots=block(hotspots),
        digest=block(digest),
        cap=4,
    )
