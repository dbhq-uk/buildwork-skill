"""Reconstruct what is running, from git, GitHub and nothing else.

Resume is deliberately built below the runner boundary. A Paseo tab, a host
subagent and a machine that was rebooted all leave the same trace: a branch,
maybe a worktree, maybe a pull request. So one implementation answers for every
runner, and it is correct after a crash, a reboot or a closed laptop - which a
cached map of agent ids would not be.

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
RUNNING = "running"          # branch exists, no PR, a worktree is checked out on it
NO_BRANCH = "not started"    # issue is in the wave, nothing exists yet
STALLED = "stalled"          # branch exists, no worktree, no PR - the agent is gone
READY = "ready"              # PR open, waiting on QC or on you
UNKNOWN_BRANCH = "orphan"    # a buildwork branch for an issue not in this session


def branch_for(number: int, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:40].strip("-")
    return f"{BRANCH_PREFIX}{number}" + (f"-{slug}" if slug else "")


def issue_from_branch(branch: str) -> int | None:
    match = BRANCH_RE.match(branch)
    return int(match.group(1)) if match else None


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
    open_pulls: list[dict],
) -> list[Item]:
    """Join the session's issues against what actually exists on disk and on GitHub."""
    by_branch_wt = {wt.get("branch"): wt.get("path") for wt in worktrees if wt.get("branch")}
    by_branch_pr = {pr.get("headRefName"): pr for pr in open_pulls}

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
        if pr:
            status = READY
        elif worktree:
            status = RUNNING
        else:
            status = STALLED
        items.append(Item(
            issue=number, status=status, branch=branch, worktree=worktree,
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
            issue=number, status=READY if pr else UNKNOWN_BRANCH, branch=branch,
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

    # Ordered by what the human should look at first.
    order = [READY, STALLED, RUNNING, UNKNOWN_BRANCH, NO_BRANCH]
    headings = {
        READY: "Waiting on you",
        STALLED: "Stalled - branch exists, no agent, no pull request",
        RUNNING: "Running",
        UNKNOWN_BRANCH: "Orphaned - a buildwork branch outside this session",
        NO_BRANCH: "Not started",
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
