"""Reconstruct what is running, from git, GitHub and nothing else.

Resume is deliberately built below the runner boundary. A Paseo tab, a host
subagent and a machine that was rebooted all leave the same trace: a branch,
maybe a worktree, maybe a pull request, open, merged or closed. So one
implementation answers for every runner, and it is correct after a crash, a
reboot or a closed laptop - which a cached map of agent ids would not be.

The branch name is the join key. That is why it is a convention rather than a
free choice: `buildwork/issue-<N>-<slug>`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

BRANCH_PREFIX = "buildwork/issue-"
BRANCH_RE = re.compile(rf"^{re.escape(BRANCH_PREFIX)}(\d+)(?:-(.*))?$")

# Every state a piece of work can be in, and what the human does about it.
RUNNING = "running"          # no PR, and an agent is working: listed live, or a worktree when no list was given
NO_BRANCH = "not started"    # issue is in the wave, nothing exists yet
STALLED = "stalled"          # branch exists, no PR, and nothing is working on it - the agent is gone
READY = "ready"              # PR open, waiting on QC or on you
UNKNOWN_BRANCH = "orphan"    # a buildwork branch for an issue not in this session
MERGED = "merged"            # PR merged - done, the local branch is left over
CLOSED = "closed"            # PR closed without merging - done, by somebody's decision

# A head branch can carry more than one pull request over its life. The one
# that describes the work now is the open one, then a merge, then a closure.
_PR_PRECEDENCE = {"OPEN": 0, "MERGED": 1, "CLOSED": 2}


def branch_for(number: int, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:40].strip("-")
    return f"{BRANCH_PREFIX}{number}" + (f"-{slug}" if slug else "")


def issue_from_branch(branch: str) -> int | None:
    match = BRANCH_RE.match(branch)
    return int(match.group(1)) if match else None


def pr_state(pr: dict) -> str:
    """OPEN, MERGED or CLOSED, as gh reports it. A record with no state is an open one."""
    return (pr.get("state") or "OPEN").upper()


def pulls_by_branch(pulls: list[dict]) -> dict[str, dict]:
    """The one pull request that speaks for each head branch."""
    best: dict[str, dict] = {}
    for pr in pulls:
        head = pr.get("headRefName")
        if not head:
            continue
        rank = (_PR_PRECEDENCE.get(pr_state(pr), 3), -int(pr.get("number") or 0))
        current = best.get(head)
        if current is None or rank < (_PR_PRECEDENCE.get(pr_state(current), 3), -int(current.get("number") or 0)):
            best[head] = pr
    return best


def _status(pr: dict | None, worktree: str | None, alive: bool | None = None) -> str:
    """What a branch is doing. `alive` is None when nobody asked the runner.

    A worktree is only a proxy for an agent. A dead agent leaves its worktree
    behind, so without the runner's list it reads as running for ever. When
    the list is given it wins: a live agent is running wherever it is, and a
    worktree with no live agent in it is stalled.
    """
    if pr:
        return {"MERGED": MERGED, "CLOSED": CLOSED}.get(pr_state(pr), READY)
    if alive is not None:
        return RUNNING if alive else STALLED
    return RUNNING if worktree else STALLED


@dataclass
class Item:
    issue: int
    status: str
    branch: str | None = None
    worktree: str | None = None
    pr: int | None = None
    pr_url: str | None = None

    def line(self) -> str:
        bits = [f"#{self.issue}", self.status]
        if self.branch:
            bits.append(self.branch)
        if self.pr:
            bits.append(f"PR #{self.pr}")
        if self.worktree:
            bits.append(Path(self.worktree).name)
        return "  ".join(bits)


def reconstruct(
    wave_issues: list[int],
    all_branches: list[str],
    worktrees: list[dict],
    pulls: list[dict],
    live: set[int] | None = None,
) -> list[Item]:
    """Join the session's issues against what actually exists on disk and on GitHub.

    `pulls` is pull requests in every state. A merged or closed one means the
    work is finished, whatever is left on disk.

    `live` is the issues the runner lists a working agent for, read by the
    orchestrator at the time of asking and never stored. None means it was not
    given, and a worktree stands in for an agent.
    """
    by_branch_wt = {wt.get("branch"): wt.get("path") for wt in worktrees if wt.get("branch")}
    by_branch_pr = pulls_by_branch(pulls)

    branch_of: dict[int, str] = {}
    for branch in all_branches:
        number = issue_from_branch(branch)
        if number is not None:
            branch_of.setdefault(number, branch)

    items: list[Item] = []
    for number in wave_issues:
        branch = branch_of.get(number)
        if not branch:
            items.append(Item(issue=number, status=NO_BRANCH))
            continue
        pr = by_branch_pr.get(branch)
        worktree = by_branch_wt.get(branch)
        alive = None if live is None else number in live
        items.append(Item(
            issue=number, status=_status(pr, worktree, alive), branch=branch, worktree=worktree,
            pr=pr.get("number") if pr else None,
            pr_url=pr.get("url") if pr else None,
        ))

    # Branches from an earlier session, or from a wave nobody recorded. Worth
    # surfacing: a stalled orphan is work somebody paid for and nobody collected.
    for number, branch in sorted(branch_of.items()):
        if number in wave_issues:
            continue
        pr = by_branch_pr.get(branch)
        items.append(Item(
            issue=number, status=_status(pr, None) if pr else UNKNOWN_BRANCH, branch=branch,
            worktree=by_branch_wt.get(branch),
            pr=pr.get("number") if pr else None,
            pr_url=pr.get("url") if pr else None,
        ))

    return items


def summarise(items: list[Item]) -> str:
    if not items:
        return "Nothing in flight. No buildwork branches, no session."

    groups: dict[str, list[Item]] = {}
    for item in items:
        groups.setdefault(item.status, []).append(item)

    # Ordered by what the human should look at first. Finished work comes last:
    # it needs nothing, and listing it as stalled was a false alarm at the end
    # of every successful wave.
    order = [READY, STALLED, RUNNING, UNKNOWN_BRANCH, NO_BRANCH, MERGED, CLOSED]
    headings = {
        READY: "Waiting on you",
        STALLED: "Stalled - no agent working on it, no pull request",
        RUNNING: "Running",
        UNKNOWN_BRANCH: "Orphaned - a buildwork branch outside this session",
        NO_BRANCH: "Not started",
        MERGED: "Merged - done, the local branch can be deleted",
        CLOSED: "Closed without merging - done, nothing to collect",
    }

    lines: list[str] = []
    for status in order:
        if status not in groups:
            continue
        lines.append(f"{headings[status]}:")
        for item in groups[status]:
            lines.append(f"  {item.line()}")
        lines.append("")
    return "\n".join(lines).rstrip()
