"""The mechanical gates, run at collection before anything is offered for merge.

Four checks, all deterministic and all cheap:

- the domain gate passes (the config's `gate` command, usually the test suite)
- the diff stays inside the files the issue declared
- no hotspot was touched without permission
- no line the branch adds looks like a credential of a known shape

The honest ceiling, which belongs in front of anyone reading a pass: mechanical
QC catches scope and spec violations. A semantically wrong change with no
covering test passes all four, and so does a secret in a shape the scan does
not know. This is a floor, not a guarantee, and a pass
here is never a substitute for reading the pull request.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

GATE_TIMEOUT = 1800  # 30 minutes; a test suite slower than this is not a gate


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Report:
    issue: int
    branch: str
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def summary(self) -> str:
        if not self.checks:
            return f"#{self.issue} ({self.branch}): nothing was checked."
        if self.passed:
            return (
                f"#{self.issue} ({self.branch}): {len(self.checks)} mechanical checks pass. "
                f"That is a floor, not a verdict - read the diff against the acceptance criteria."
            )
        return f"#{self.issue} ({self.branch}): " + "; ".join(
            f"{c.name} failed - {c.detail}" for c in self.failures
        )


def _under(path: str, declared: str) -> bool:
    norm = declared.rstrip("/")
    return path == norm or path.startswith(norm + "/")


def scope_check(changed: list[str], declared: tuple[str, ...]) -> Check:
    """Every changed file must sit under something the issue named.

    An issue that declared nothing is not failed for it. There is no scope to
    check against, and failing every under-specified issue would train people
    to declare a directory and call it done. It is reported as unchecked.
    """
    if not declared:
        return Check("scope", True, "issue declared no paths, so scope was not checked")
    stray = [f for f in changed if not any(_under(f, d) for d in declared)]
    if stray:
        shown = ", ".join(stray[:5]) + ("..." if len(stray) > 5 else "")
        return Check("scope", False, f"{len(stray)} file(s) outside the declared scope: {shown}")
    return Check("scope", True, f"{len(changed)} file(s), all within scope")


def hotspot_check(changed: list[str], hotspots: tuple[str, ...], allowed: tuple[str, ...] = ()) -> Check:
    """No hotspot may be touched unless this issue was the one sent to touch it."""
    if not hotspots:
        return Check("hotspots", True, "none configured")
    hit = [
        spot for spot in hotspots
        if spot not in allowed and any(_under(f, spot) for f in changed)
    ]
    if hit:
        return Check(
            "hotspots", False,
            f"touched {', '.join(hit)} without being the issue sent to change it - "
            f"this is the file class that conflicts on every parallel branch",
        )
    return Check("hotspots", True, "no unpermitted hotspot touched")


# Credential shapes with a fixed prefix or a fixed header, so a match is
# almost never anything else. A generic "long random string" rule would fail
# every branch that adds a hash or a fixture, and a check that cries wolf is
# switched off. What matched is named; the value never is.
SECRETS = (
    ("a private key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY(?: BLOCK)?-----")),
    ("an AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("a GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})")),
    ("a Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("a Stripe live key", re.compile(r"\b[rs]k_live_[0-9A-Za-z]{20,}")),
    ("an Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("an OpenAI project key", re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}")),
)


def secret_check(added: list[tuple[str, str]]) -> Check:
    """No line the branch adds may look like a known credential.

    `added` is (path, line) for every added line in the branch's diff. A
    worker that commits a token passes every other gate, and a push has
    already exposed it, so the failure says to rotate it, not only remove it.
    """
    hits: list[str] = []
    for path, line in added:
        for name, pattern in SECRETS:
            if pattern.search(line):
                hit = f"{name} in {path or 'an added file'}"
                if hit not in hits:
                    hits.append(hit)
    if hits:
        shown = "; ".join(hits[:5]) + ("..." if len(hits) > 5 else "")
        return Check(
            "secrets", False,
            f"{shown}. Take it out of the branch, and rotate it: pushing it has already exposed it",
        )
    return Check("secrets", True, f"no known credential shape in {len(added)} added line(s)")


def run_gate(command: str | None, cwd: Path) -> Check:
    """Run the configured domain gate in the worker's worktree."""
    if not command:
        return Check(
            "gate", True,
            "no gate configured, so nothing mechanical verified this branch works",
        )
    try:
        proc = subprocess.run(
            command, shell=True, cwd=cwd, capture_output=True, text=True, timeout=GATE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return Check("gate", False, f"timed out after {GATE_TIMEOUT}s")
    if proc.returncode == 0:
        return Check("gate", True, "passed")
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    return Check("gate", False, f"exit {proc.returncode}: " + " / ".join(tail[-3:]))


def check(
    issue: int,
    branch: str,
    changed: list[str],
    declared: tuple[str, ...],
    hotspots: tuple[str, ...],
    allowed_hotspots: tuple[str, ...] = (),
    gate_command: str | None = None,
    worktree: Path | None = None,
    added: list[tuple[str, str]] | None = None,
) -> Report:
    report = Report(issue=issue, branch=branch)
    report.checks.append(scope_check(changed, declared))
    report.checks.append(hotspot_check(changed, hotspots, allowed_hotspots))
    if added is not None:
        report.checks.append(secret_check(added))
    if worktree is not None:
        report.checks.append(run_gate(gate_command, worktree))
    return report
