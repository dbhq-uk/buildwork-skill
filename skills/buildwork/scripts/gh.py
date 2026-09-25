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
from dataclasses import dataclass, field
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


def commits_ahead(cwd: Path, base: str, branch: str) -> int:
    """Commits on `branch` that `base` does not have."""
    out = _run(["git", "rev-list", "--count", f"{base}..{branch}"], cwd=cwd)
    return int(out.strip() or 0)


def changed_files(cwd: Path, base: str, branch: str) -> list[str]:
    """Files the branch changes relative to the merge base with `base`.

    Three dots, deliberately. Two dots would also list everything that landed
    on base since the branch was cut, which is somebody else's work and would
    make every scope check fail the moment base moved.
    """
    out = _run(["git", "diff", "--name-only", f"{base}...{branch}"], cwd=cwd)
    return [line.strip() for line in out.splitlines() if line.strip()]


def trial_merge(cwd: Path, ours: str, theirs: str) -> tuple[str, list[str]]:
    """Merge `theirs` into `ours` in the object store only: (tree, conflicted paths).

    `git merge-tree --write-tree` computes the merge and writes the result as
    objects. It moves no ref and touches no worktree and no index, so this
    predicts a conflict without merging anything. Exit 1 means conflicts;
    anything else non-zero means git could not do it, and raises.
    """
    try:
        proc = subprocess.run(
            ["git", "merge-tree", "--write-tree", "--name-only", "--no-messages", ours, theirs],
            cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise GhError(f"git merge-tree could not run: {exc}") from exc
    if proc.returncode not in (0, 1):
        raise GhError(f"git merge-tree failed ({proc.returncode}): {proc.stderr.strip()}")
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    tree = lines[0] if lines else ""
    conflicts = list(dict.fromkeys(lines[1:])) if proc.returncode == 1 else []
    return tree, conflicts


def trial_commit(cwd: Path, tree: str, parent: str) -> str:
    """A commit object for a trial merge's tree, so the next trial can build on it.

    `git merge-tree` in the git this runs on takes commits, not trees. The
    object is written and nothing points at it: no ref moves, and git's
    garbage collection removes it later.
    """
    return _run(
        ["git", "-c", "user.name=buildwork", "-c", "user.email=buildwork@localhost",
         "commit-tree", tree, "-p", parent, "-m", "buildwork trial merge"],
        cwd=cwd,
    ).strip()


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

ISSUE_LIST_FIELDS = "number,title,body,labels,url"


def open_issues(cwd: Path, limit: int = 200, blockers: bool = False) -> list[dict]:
    """Every open issue. Raises GhError, with gh's stderr, when gh fails.

    With `blockers`, each issue also carries gh's `blockedBy` field, so the
    whole dependency graph comes back in this one call. A gh too old to have
    that field fails the call; it is asked again without it, and the issues
    come back with no `blockedBy` key, which `dependencies` reads as "this
    source did not answer".
    """
    args = ["gh", "issue", "list", "--state", "open", "--limit", str(limit), "--json"]
    if blockers:
        try:
            return _json([*args, ISSUE_LIST_FIELDS + ",blockedBy"], cwd=cwd) or []
        except GhError:
            pass
    return _json([*args, ISSUE_LIST_FIELDS], cwd=cwd) or []


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


# `after #N` is not here on purpose. "Tidy up after #12 lands" and "found
# after #12 shipped" are ordinary sentences, and reading them as edges invents
# dependencies nobody declared.
BLOCKED_BY_PROSE = re.compile(r"\b(?:blocked by|depends on)\s+#(\d+)", re.I)

# Where a dependency graph came from. The first two are GitHub's own links;
# the last is a regex over the issue body, used only when neither answered.
SOURCE_FIELD = "blockedBy"
SOURCE_REST = "rest"
SOURCE_BODY = "body"

GITHUB_REPO = re.compile(r"(?:api\.github\.com/repos/|github\.com/)([^/\s]+/[^/\s]+?)(?:/|$)")


@dataclass(frozen=True)
class Blocker:
    number: int
    repo: str = ""   # "" for this repository, "owner/name" for another one
    state: str = ""  # "OPEN" or "CLOSED" when the source said, "" when it did not

    def __str__(self) -> str:
        return f"{self.repo}#{self.number}" if self.repo else f"#{self.number}"


@dataclass
class Dependencies:
    blockers: list[Blocker] = field(default_factory=list)
    source: str = SOURCE_BODY
    problem: str = ""  # why GitHub's own links could not be read, when they were not

    @property
    def local(self) -> list[int]:
        """Blockers in this repository. One in another repository is never a local number."""
        return sorted({b.number for b in self.blockers if not b.repo})


def _repo_in(url: str) -> str:
    match = GITHUB_REPO.search(url or "")
    return match.group(1) if match else ""


def _blocker(number, repo: str, state: str, home: str) -> Blocker:
    # With no repository to compare, a blocker is not assumed to be local.
    # Reading `other/repo#12` as local #12 is the mistake this guards against.
    foreign = not repo or not home or repo.lower() != home.lower()
    return Blocker(
        number=int(number),
        repo=(repo or "another repository") if foreign else "",
        state=(state or "").upper(),
    )


def _from_field(field_value: dict, home: str) -> list[Blocker]:
    out = []
    for node in field_value.get("nodes") or []:
        if not isinstance(node, dict) or "number" not in node:
            continue
        repo = (node.get("repository") or {}).get("nameWithOwner") or _repo_in(node.get("url", ""))
        out.append(_blocker(node["number"], repo, node.get("state", ""), home))
    return out


def _from_rest(cwd: Path, number: int, home: str) -> list[Blocker]:
    """Every blocker from the REST endpoint. Raises GhError when it does not answer.

    `--paginate` because the endpoint returns 30 a page, and `--slurp` because
    without it the pages are printed back to back and are not one JSON value.
    """
    pages = _json(
        ["gh", "api", "--paginate", "--slurp",
         f"repos/{{owner}}/{{repo}}/issues/{number}/dependencies/blocked_by?per_page=100"],
        cwd=cwd,
    ) or []
    out = []
    for page in pages:
        for item in page if isinstance(page, list) else []:
            if not isinstance(item, dict) or "number" not in item:
                continue
            repo = _repo_in(item.get("repository_url", "")) or _repo_in(item.get("html_url", ""))
            out.append(_blocker(item["number"], repo, item.get("state", ""), home))
    return out


def dependencies(cwd: Path, issue: dict) -> Dependencies:
    """What this issue is blocked by, and which source said so.

    First gh's `blockedBy` field, when the issue came from `open_issues(...,
    blockers=True)` and the field lists every blocker. Then the REST
    endpoint, paginated, with its exit code checked. Only when neither
    answers, `Blocked by #N` lines in the body, with the reason recorded in
    `problem` so the caller can say the graph was not read. An edge missed
    here becomes two agents dispatched into a dependency they were meant to
    run in sequence, so the caller is always told which source answered.
    """
    number = int(issue["number"])
    home = _repo_in(issue.get("url", "")) or repo_name(cwd)

    value = issue.get("blockedBy")
    if isinstance(value, dict):
        found = _from_field(value, home)
        total = value.get("totalCount")
        # gh asks for the first 50. Past that, the field is only a sample.
        if not isinstance(total, int) or total <= len(found):
            return Dependencies(blockers=found, source=SOURCE_FIELD)

    try:
        return Dependencies(blockers=_from_rest(cwd, number, home), source=SOURCE_REST)
    except GhError as exc:
        prose = sorted({int(m) for m in BLOCKED_BY_PROSE.findall(issue.get("body") or "")})
        return Dependencies(
            blockers=[Blocker(number=n) for n in prose], source=SOURCE_BODY, problem=str(exc),
        )
