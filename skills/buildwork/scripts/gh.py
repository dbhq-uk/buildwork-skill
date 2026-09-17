"""Every `gh` and `git` call, in one place.

Kept thin on purpose. Everything above this module works on plain dicts, so
the planning, hotspot, QC and ordering logic is testable without a network,
a token, or a GitHub account. The tests put a fake `gh` on PATH; they do not
mock this module.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

TIMEOUT = 60


class GhError(Exception):
    """A gh or git call failed. The message carries stderr, not a summary of it."""


def _run(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    try:
        proc = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise GhError(f"{args[0]} is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GhError(f"{' '.join(args[:3])} timed out after {TIMEOUT}s") from exc
    if check and proc.returncode != 0:
        raise GhError(f"{' '.join(args[:3])} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def _json(args: list[str], cwd: Path | None = None, default=None):
    out = _run(args, cwd=cwd, check=default is None)
    if not out.strip():
        return default
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        if default is not None:
            return default
        raise GhError(f"{' '.join(args[:3])} returned output that is not JSON")


# --- git ------------------------------------------------------------------

def repo_root(start: Path) -> Path:
    return Path(_run(["git", "rev-parse", "--show-toplevel"], cwd=start).strip())


def branches(cwd: Path) -> list[str]:
    out = _run(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"], cwd=cwd)
    return [line.strip() for line in out.splitlines() if line.strip()]


def worktrees(cwd: Path) -> list[dict]:
    """Every worktree, as {path, branch}. `git worktree list --porcelain` is the only stable form."""
    out = _run(["git", "worktree", "list", "--porcelain"], cwd=cwd)
    trees, current = [], {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            if current:
                trees.append(current)
            current = {"path": line[len("worktree "):].strip(), "branch": None}
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):].strip().removeprefix("refs/heads/")
    if current:
        trees.append(current)
    return trees


def changed_files(cwd: Path, base: str, branch: str) -> list[str]:
    """Files the branch changes relative to the merge base with `base`.

    Three dots, deliberately. Two dots would also list everything that landed
    on base since the branch was cut, which is somebody else's work and would
    make every scope check fail the moment base moved.
    """
    out = _run(["git", "diff", "--name-only", f"{base}...{branch}"], cwd=cwd)
    return [line.strip() for line in out.splitlines() if line.strip()]


def diff_size(cwd: Path, base: str, branch: str) -> int:
    """Total lines added plus removed. Used only to break ties in merge order."""
    out = _run(["git", "diff", "--numstat", f"{base}...{branch}"], cwd=cwd)
    total = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            for n in parts[:2]:
                if n.isdigit():
                    total += int(n)
    return total


# --- gh -------------------------------------------------------------------

def open_issues(cwd: Path, limit: int = 200) -> list[dict]:
    return _json(
        ["gh", "issue", "list", "--state", "open", "--limit", str(limit),
         "--json", "number,title,body,labels,url"],
        cwd=cwd, default=[],
    ) or []


def issue(cwd: Path, number: int) -> dict:
    return _json(
        ["gh", "issue", "view", str(number), "--json", "number,title,body,labels,url,state"],
        cwd=cwd,
    )


def open_pulls(cwd: Path, limit: int = 100) -> list[dict]:
    return _json(
        ["gh", "pr", "list", "--state", "open", "--limit", str(limit),
         "--json", "number,title,headRefName,url,isDraft,body"],
        cwd=cwd, default=[],
    ) or []


BLOCKED_BY_PROSE = re.compile(r"\b(?:blocked by|depends on|after)\s+#(\d+)", re.I)


def blocked_by(cwd: Path, number: int, body: str = "") -> list[int]:
    """Issue numbers this issue is blocked by.

    Native GitHub issue dependencies first. If that endpoint is unavailable -
    an older GitHub Enterprise, a repo without the feature, a gh too old - fall
    back to reading `Blocked by #N` out of the body.

    The fallback is not as good and the caller is told which one answered, so a
    missing edge is visible rather than silently assumed absent. An edge this
    module fails to find becomes two agents dispatched into a dependency they
    were supposed to run in sequence.
    """
    data = _json(
        ["gh", "api", f"repos/{{owner}}/{{repo}}/issues/{number}/dependencies/blocked_by"],
        cwd=cwd, default=[],
    )
    if isinstance(data, list) and data:
        return sorted({int(item["number"]) for item in data if "number" in item})
    return sorted({int(m) for m in BLOCKED_BY_PROSE.findall(body or "")})


def pr_for_branch(pulls: list[dict], branch: str) -> dict | None:
    for pr in pulls:
        if pr.get("headRefName") == branch:
            return pr
    return None
