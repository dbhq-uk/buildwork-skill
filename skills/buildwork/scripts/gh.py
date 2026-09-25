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

# The remote workers are cut from and pull requests go to. A worker cut from a
# local branch starts from wherever that clone last pulled, which after a
# merge on GitHub is behind the work it is meant to build on.
REMOTE = "origin"


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
    """Run a command and parse its JSON.

    Passing `default` means a failure is an acceptable answer and the exit
    code is not checked. Only pass one where "gh could not say" and "there is
    nothing" really are the same thing. A list call is never one of those: a
    failed `gh issue list` that reads as `[]` tells the user there is nothing
    to run, when the truth is that gh could not answer.
    """
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


def remote_base(base: str) -> str:
    """`origin/<base>`: the ref a worker is cut from, never the local branch."""
    return f"{REMOTE}/{base}"


def fetch_base(cwd: Path, base: str) -> None:
    """Bring `origin/<base>` up to date. Raises GhError, with git's message, when it cannot.

    Only the remote-tracking ref moves. The local base branch, the working
    tree and every worker's branch are left exactly where they were.
    """
    _run(["git", "fetch", "--quiet", REMOTE, base], cwd=cwd)


def base_ref(cwd: Path, base: str) -> str:
    """What to diff a worker's branch against: `origin/<base>` if it exists, else local `base`.

    Diffing against a local base that is behind the remote lists every commit
    merged on GitHub since the last pull as the worker's own change, so a
    clean branch fails its scope check the moment another wave lands.
    """
    out = _run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote_base(base)}"],
        cwd=cwd, check=False,
    )
    return remote_base(base) if out.strip() else base


def behind_remote(cwd: Path, base: str) -> int | None:
    """Commits on `origin/<base>` that local `base` lacks. None if either ref is missing."""
    out = _run(
        ["git", "rev-list", "--count", f"refs/heads/{base}..refs/remotes/{remote_base(base)}"],
        cwd=cwd, check=False,
    )
    return int(out.strip()) if out.strip().isdigit() else None


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
    """Every open issue. Raises GhError, with gh's stderr, when gh fails."""
    return _json(
        ["gh", "issue", "list", "--state", "open", "--limit", str(limit),
         "--json", "number,title,body,labels,url"],
        cwd=cwd,
    ) or []


def issue(cwd: Path, number: int) -> dict:
    return _json(
        ["gh", "issue", "view", str(number), "--json", "number,title,body,labels,url,state"],
        cwd=cwd,
    )


def pulls(cwd: Path, limit: int = 200) -> list[dict]:
    """Recent pull requests in every state, newest first. Raises GhError when gh fails.

    Every state, not only open. After a squash merge the local branch is
    usually still there, and with only open pull requests to match it against
    a finished issue looks exactly like an agent that died: a branch with no
    worktree and no pull request.
    """
    return _json(
        ["gh", "pr", "list", "--state", "all", "--limit", str(limit),
         "--json", "number,title,headRefName,url,isDraft,state"],
        cwd=cwd,
    ) or []


def auth_status(cwd: Path) -> None:
    """Raise GhError, carrying gh's own message, unless gh is logged in with a working token."""
    _run(["gh", "auth", "status"], cwd=cwd)


def repo_name(cwd: Path) -> str:
    """The `owner/repo` gh resolves this clone to. Raises GhError if it cannot."""
    data = _json(["gh", "repo", "view", "--json", "nameWithOwner"], cwd=cwd)
    if not isinstance(data, dict) or not data.get("nameWithOwner"):
        raise GhError("gh repo view did not name a repository")
    return data["nameWithOwner"]


def remotes(cwd: Path) -> list[str]:
    return [line.strip() for line in _run(["git", "remote"], cwd=cwd).splitlines() if line.strip()]


def default_remote_set(cwd: Path) -> bool:
    """Whether `gh repo set-default` has been run in this clone.

    gh records the choice as `remote.<name>.gh-resolved` in the git config.
    Without it, and with more than one remote, gh picks a remote by its own
    precedence and says nothing, so every answer may be about another
    repository.
    """
    out = _run(["git", "config", "--get-regexp", r"^remote\..*\.gh-resolved$"], cwd=cwd, check=False)
    return bool(out.strip())


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
