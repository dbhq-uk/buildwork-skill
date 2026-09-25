#!/usr/bin/env python3
"""buildwork - plan, check and order parallel agent work against a repository's issues.

This script does the deterministic half and nothing else. It decides what may
safely run at once, writes each worker's brief, checks a finished branch, and
proposes a merge order.

It never dispatches an agent, because dispatch goes through MCP tools or the
host's own subagent surface and a Python script cannot call either. It never
merges, because a human merges. It has no verb for either, which is what makes
those promises hold rather than depend on restraint.

  plan     work out the waves, or refuse to fan out
  brief    the whole of what one worker is told
  qc       the mechanical gates against a finished branch
  order    the proposed merge order, with reasons
  status   what is running, reconstructed from git and GitHub
  init     write a starter config and suggest hotspots
  doctor   report drift between the session, the branches and GitHub
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import config as config_mod   # noqa: E402
import digest as digest_mod   # noqa: E402
import gh                     # noqa: E402
import order as order_mod     # noqa: E402
import qc as qc_mod           # noqa: E402
import roadmap as roadmap_mod # noqa: E402
import session as session_mod # noqa: E402
import state                  # noqa: E402
import waves as waves_mod     # noqa: E402


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def load_ctx(path: str) -> tuple[Path, config_mod.Config]:
    try:
        root = gh.repo_root(Path(path).resolve())
    except gh.GhError as exc:
        fail(str(exc))
    try:
        return root, config_mod.load(root)
    except config_mod.ConfigError as exc:
        fail(str(exc))


# --- plan -----------------------------------------------------------------

def cmd_plan(args: argparse.Namespace) -> int:
    root, cfg = load_ctx(args.path)
    runner = cfg.runner if cfg.runner != "auto" else (args.runner or "subagent")
    cap = cfg.cap_for(runner)

    # Every wave is cut from origin/<base> as it is now. Without the fetch, a
    # wave planned after the last one merged on GitHub starts from a base that
    # does not contain it.
    cut_from = gh.remote_base(cfg.base)
    try:
        gh.fetch_base(root, cfg.base)
    except gh.GhError as exc:
        fail(
            f"Could not fetch {cut_from}, so a wave would be cut from a base that may be "
            f"missing merged work. Fix the fetch and plan again.\n{exc}"
        )

    issues = gh.open_issues(root)
    by_number = {int(i["number"]): i for i in issues}

    board = roadmap_mod.load(cfg.roadmap_path, fallback_issues=issues)

    if args.issues:
        wanted = [int(n) for n in args.issues.split(",") if n.strip()]
    else:
        wanted = [e.number for e in board.runnable]

    missing = [n for n in wanted if n not in by_number]
    selected = [by_number[n] for n in wanted if n in by_number]

    graph, graph_known = {}, False
    for issue in selected:
        try:
            deps = gh.blocked_by(root, int(issue["number"]), issue.get("body") or "")
            graph[int(issue["number"])] = deps
            graph_known = True
        except gh.GhError:
            graph[int(issue["number"])] = []

    candidates = waves_mod.build_candidates(selected, cfg.hotspots, root)
    plan = waves_mod.plan(candidates, graph, cap=cap, graph_is_known=graph_known)

    if board.note:
        plan.assumptions.append(board.note)
    if missing:
        plan.warnings.append(
            "In the roadmap but not open on GitHub: "
            + ", ".join(f"#{n}" for n in missing) + ". Skipped."
        )

    payload = {
        "goal": args.goal,
        "runner": runner,
        "cap": cap,
        "base": cfg.base,
        "base_ref": cut_from,
        "source": board.source,
        "refusal": plan.refusal,
        "waves": [
            [
                {
                    "issue": n,
                    "title": by_number[n].get("title", ""),
                    "branch": state.branch_for(n, by_number[n].get("title", "")),
                    "hotspots": list(next(c.hotspots for c in candidates if c.number == n)),
                }
                for n in wave
            ]
            for wave in plan.waves
        ],
        "warnings": plan.warnings,
        "assumptions": plan.assumptions,
        "cycles": plan.cycles,
    }

    if args.save and not plan.refusal:
        session_mod.save(root, session_mod.Session(
            repo=root.name, goal=args.goal or "", runner=runner,
            issues=plan.dispatched, waves=plan.waves,
            hotspots={
                str(c.number): list(c.hotspots)
                for c in candidates if c.hotspots and c.number in plan.dispatched
            },
        ))

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(_render_plan(payload))
    return 0


def _render_plan(p: dict) -> str:
    lines = []
    if p["goal"]:
        lines.append(f"Goal: {p['goal']}")
    lines.append(f"Runner: {p['runner']}, up to {p['cap']} at once, cut from {p['base_ref']}. Order from {p['source']}.")
    lines.append("")

    if p["refusal"]:
        lines.append("DO NOT FAN OUT")
        lines.append(p["refusal"])
        return "\n".join(lines + [""] + p["warnings"] + p["assumptions"]).rstrip()

    for n, wave in enumerate(p["waves"], 1):
        label = f"Wave {n}" + (f" ({len(wave)} in parallel)" if len(wave) > 1 else " (alone)")
        lines.append(label + ":")
        for item in wave:
            spots = f"  [hotspot: {', '.join(item['hotspots'])}]" if item["hotspots"] else ""
            lines.append(f"  #{item['issue']}  {item['title']}{spots}")
            lines.append(f"      {item['branch']}")
        lines.append("")

    for warning in p["warnings"]:
        lines.append(f"! {warning}")
    for assumption in p["assumptions"]:
        lines.append(f"~ {assumption}")
    return "\n".join(lines).rstrip()


# --- brief ----------------------------------------------------------------

def cmd_brief(args: argparse.Namespace) -> int:
    root, cfg = load_ctx(args.path)
    try:
        issue = gh.issue(root, args.issue)
    except gh.GhError as exc:
        fail(str(exc))

    text, problems = digest_mod.collect(root, cfg.digest)
    for problem in problems:
        print(f"! digest: {problem}", file=sys.stderr)

    declared = waves_mod.declared_files(issue.get("body") or "", root)
    allowed = tuple(args.allow_hotspot or ())
    branch = args.branch or state.branch_for(args.issue, issue.get("title", ""))

    print(digest_mod.brief(
        issue=issue, base=cfg.base, branch=branch, digest_text=text,
        declared=declared, allowed_hotspots=allowed, cut_from=gh.remote_base(cfg.base),
        runner=_brief_runner(args, cfg, root),
    ))
    return 0


def _brief_runner(args: argparse.Namespace, cfg: config_mod.Config, root: Path) -> str:
    """Which runner this brief is for: the flag, then the saved session, then the config.

    It changes what the worker is told first. A subagent's host names its
    branch and picks its base, so that brief opens by putting both right; a
    Paseo worker is already on the right branch. With `runner = "auto"` and
    nothing saved, guessing would send one of them the wrong instructions.
    """
    if args.runner:
        return args.runner
    sess = session_mod.load(root)
    if sess and sess.runner in config_mod.RUNNER_WAVE_CAP:
        return sess.runner
    if cfg.runner in config_mod.RUNNER_WAVE_CAP:
        return cfg.runner
    fail(
        "brief needs to know the runner, because a subagent worker is told to rename its "
        "branch first. Pass --runner paseo or --runner subagent, or run plan --save first."
    )


# --- qc -------------------------------------------------------------------

def cmd_qc(args: argparse.Namespace) -> int:
    root, cfg = load_ctx(args.path)
    try:
        issue = gh.issue(root, args.issue)
    except gh.GhError as exc:
        fail(str(exc))

    branch = args.branch or state.branch_for(args.issue, issue.get("title", ""))
    if branch not in gh.branches(root):
        fail(f"No branch {branch}. Nothing to check.")

    changed = gh.changed_files(root, gh.base_ref(root, cfg.base), branch)
    declared = waves_mod.declared_files(issue.get("body") or "", root)

    worktree = None
    if not args.no_gate:
        for tree in gh.worktrees(root):
            if tree.get("branch") == branch:
                worktree = Path(tree["path"])
                break
        if worktree is None and cfg.gate:
            print(
                f"! No worktree is checked out on {branch}, so the gate ({cfg.gate}) was not run. "
                f"Scope and hotspots were still checked.",
                file=sys.stderr,
            )

    # The plan's permission, saved at `plan --save`, plus any given here. The
    # orchestrator runs `qc N` bare at collection, so without the saved one
    # the branch sent to change a hotspot would fail for doing exactly that.
    sess = session_mod.load(root)
    allowed = tuple(dict.fromkeys(
        tuple(args.allow_hotspot or ()) + (sess.allowed_hotspots(args.issue) if sess else ())
    ))
    report = qc_mod.check(
        issue=args.issue, branch=branch, changed=changed, declared=declared,
        hotspots=cfg.hotspots, allowed_hotspots=allowed,
        gate_command=cfg.gate, worktree=worktree,
    )

    for check in report.checks:
        print(f"[{'pass' if check.passed else 'FAIL'}] {check.name}: {check.detail}")
    print()
    print(report.summary())
    return 0 if report.passed else 2


# --- order ----------------------------------------------------------------

def cmd_order(args: argparse.Namespace) -> int:
    root, cfg = load_ctx(args.path)
    sess = session_mod.load(root)
    pulls = state.pulls_by_branch(gh.pulls(root))

    numbers = sess.issues if sess else sorted(
        {n for n in (state.issue_from_branch(b) for b in gh.branches(root)) if n}
    )
    if not numbers:
        fail("No session and no buildwork branches. Nothing to order.")

    base = gh.base_ref(root, cfg.base)
    items = []
    finished = 0
    for number in numbers:
        branch = next(
            (b for b in gh.branches(root) if state.issue_from_branch(b) == number), None
        )
        if not branch:
            continue
        pr = pulls.get(branch)
        if pr and state.pr_state(pr) != "OPEN":
            # Merged or closed, so it is finished. Offering a merged branch
            # again asks for work already on the base; offering a closed one
            # overrides somebody's decision not to merge it.
            finished += 1
            continue
        # No fallback to an empty body. With no body the issue declares no
        # paths, the scope check reports nothing to check, and a branch gh
        # could not read about is offered for merge.
        body = gh.issue(root, number).get("body") or ""
        declared = waves_mod.declared_files(body, root)
        changed = gh.changed_files(root, base, branch)
        # Without the plan's permission, the one branch sent to change a
        # hotspot fails the hotspot check here and is held back, and the
        # first ordering rule, hotspot first, can never fire.
        report = qc_mod.check(
            issue=number, branch=branch, changed=changed, declared=declared,
            hotspots=cfg.hotspots,
            allowed_hotspots=sess.allowed_hotspots(number) if sess else (),
        )
        items.append(order_mod.Ready(
            issue=number, branch=branch,
            pr=pr.get("number") if pr else None,
            hotspots=waves_mod.hotspots_touched(tuple(changed), cfg.hotspots),
            blocked_by=tuple(gh.blocked_by(root, number, body)),
            diff_size=gh.diff_size(root, base, branch),
            qc_passed=report.passed,
        ))

    if not items and finished:
        print("Nothing left to merge. Every pull request in this set is merged or closed.")
        return 0

    positions, notes = order_mod.propose(items)
    print(order_mod.render(positions, notes))
    return 0


# --- status ---------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    root, cfg = load_ctx(args.path)
    sess = session_mod.load(root)

    # Everything is read before anything is printed. A gh failure raises and
    # stops the command with gh's own message, rather than half a report.
    all_branches = gh.branches(root)
    worktrees = gh.worktrees(root)
    pulls = gh.pulls(root)

    if sess:
        stale = "  (STALE - started " + sess.age_text() + ", check it is still what you want)" if sess.stale else ""
        print(f"Session: {sess.goal or '(no goal recorded)'}{stale}")
        print(f"Started {sess.age_text()}, runner {sess.runner}.")
        print()
    else:
        print("No session record. Reconstructing from branches alone.\n")

    items = state.reconstruct(
        wave_issues=sess.issues if sess else [],
        all_branches=all_branches,
        worktrees=worktrees,
        pulls=pulls,
    )
    print(state.summarise(items))
    return 0


# --- init -----------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    try:
        root = gh.repo_root(Path(args.path).resolve())
    except gh.GhError as exc:
        fail(str(exc))

    path = root / config_mod.CONFIG_PATH
    if path.exists() and not args.force:
        fail(f"{config_mod.CONFIG_PATH} already exists. Pass --force to overwrite it.")

    suggested = _suggest_hotspots(root)
    digest = [name for name in ("CLAUDE.md", "AGENTS.md", "CONTRIBUTING.md") if (root / name).is_file()]
    base = _default_base(root)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config_mod.starter(base=base, hotspots=suggested, digest=digest), encoding="utf-8")

    print(f"Wrote {config_mod.CONFIG_PATH} with enabled = false.")
    print()
    print(f"Base branch: {base}")
    print(f"Digest files: {', '.join(digest) if digest else 'none found'}")
    if suggested:
        print("Suggested hotspots, from the files most often touched in recent merges:")
        for name in suggested:
            print(f"  {name}")
        print()
        print("Check these. They are the files most changed, which is a good proxy for")
        print("the files two parallel branches will fight over, but it is only a proxy.")
    print()
    print("Nothing runs until you set enabled = true.")
    return 0


def _default_base(root: Path) -> str:
    try:
        out = gh._run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=root, check=False)
        name = out.strip().removeprefix("origin/")
        if name:
            return name
    except gh.GhError:
        pass
    return "main"


def _suggest_hotspots(root: Path, commits: int = 200, top: int = 6) -> list[str]:
    """The files touched most often recently, as a starting list of conflict-prone paths."""
    try:
        out = gh._run(
            ["git", "log", f"-n{commits}", "--name-only", "--pretty=format:", "--no-merges"],
            cwd=root, check=False,
        )
    except gh.GhError:
        return []
    counts = collections.Counter(
        line.strip() for line in out.splitlines() if line.strip() and not line.startswith(" ")
    )
    # Directories and generated files are noise. A hotspot worth naming is a
    # single file several unrelated changes keep landing in.
    return [
        name for name, count in counts.most_common(top * 3)
        if count >= 3 and not name.endswith((".lock", ".png", ".svg", ".jpg"))
    ][:top]


# --- doctor ---------------------------------------------------------------

def cmd_doctor(args: argparse.Namespace) -> int:
    root, cfg = load_ctx(args.path)
    problems: list[str] = []

    if not cfg.roadmap_path.is_file():
        problems.append(f"No {cfg.roadmap}, so issue order is unknown and every plan guesses it.")
    if not cfg.gate:
        problems.append("No `gate` configured, so nothing mechanical verifies a branch works before you merge it.")
    for spot in cfg.hotspots:
        if not (root / spot).exists():
            problems.append(f"Hotspot `{spot}` does not exist. A stale hotspot blocks waves for no reason.")
    for name in cfg.digest:
        if not (root / name).is_file():
            problems.append(f"Digest file `{name}` does not exist and will be missing from every worker's brief.")

    sess = session_mod.load(root)
    if sess and sess.stale:
        problems.append(f"Session record is {sess.age_text()} old: {sess.goal!r}. Probably finished; clear it.")

    problems += _base_checks(root, cfg.base)

    gh_problems, gh_error = _gh_checks(root)
    problems += gh_problems
    pulls: list[dict] = []
    if gh_error is None:
        try:
            pulls = gh.pulls(root)
        except gh.GhError as exc:
            gh_error = str(exc)

    if gh_error is not None:
        # Reconciling against a gh that failed is how every branch came to look
        # stranded. Report what is known and stop.
        problems.append(
            "Branches and pull requests were not checked, because gh could not answer. "
            "Every other command will stop on the same error until gh works."
        )
        print(f"{len(problems)} thing(s) to look at:\n")
        for problem in problems:
            print(f"- {problem}")
        print(f"\ngh failed: {gh_error}", file=sys.stderr)
        return 1

    branches = gh.branches(root)
    worktrees = gh.worktrees(root)
    items = state.reconstruct(sess.issues if sess else [], branches, worktrees, pulls)

    for item in items:
        if item.status == state.STALLED:
            problems.append(
                f"#{item.issue} on {item.branch} has no worktree and no pull request. "
                f"An agent started it and is gone; the work is stranded."
            )
        if item.status == state.UNKNOWN_BRANCH:
            problems.append(
                f"{item.branch} is a buildwork branch for #{item.issue}, which is not in this session."
            )

    if not problems:
        print("No drift found.")
        return 0

    print(f"{len(problems)} thing(s) to look at:\n")
    for problem in problems:
        print(f"- {problem}")
    return 0


def _base_checks(root: Path, base: str) -> list[str]:
    """Whether local `base` has fallen behind the remote one.

    buildwork cuts and compares against origin/<base>, so this is not a fault
    in buildwork. It is the trap for everything else: a Paseo workspace given
    a bare `main`, a diff run by hand, a human checking a branch locally.
    """
    remote = gh.remote_base(base)
    problems: list[str] = []
    try:
        gh.fetch_base(root, base)
    except gh.GhError as exc:
        problems.append(f"Could not fetch {remote}, so the check below used the last fetch. {exc}")
    behind = gh.behind_remote(root, base)
    if behind:
        problems.append(
            f"Local `{base}` is {behind} commit(s) behind `{remote}`. A worker cut from local "
            f"`{base}`, or a diff against it, misses that work. Dispatch from `{remote}`, "
            f"which is what `plan` names."
        )
    return problems


def _gh_checks(root: Path) -> tuple[list[str], str | None]:
    """Problems with gh itself, and gh's own error if it cannot be used at all.

    Every other command trusts gh's answers. These are the ways it answers
    wrongly or not at all: no working login, a clone gh cannot map to a
    repository, and a clone with several remotes where gh has picked one on
    its own.
    """
    try:
        gh.auth_status(root)
    except gh.GhError as exc:
        return ["gh is not logged in, or its token no longer works. Run `gh auth login`."], str(exc)
    try:
        name = gh.repo_name(root)
    except gh.GhError as exc:
        return [
            "gh cannot tell which GitHub repository this clone is. Check `git remote -v`, "
            "or run `gh repo set-default`."
        ], str(exc)

    names = gh.remotes(root)
    if len(names) > 1 and not gh.default_remote_set(root):
        return [
            f"This clone has {len(names)} remotes ({', '.join(names)}) and no default, so gh "
            f"chose {name} on its own. If that is not the repository you mean, run "
            f"`gh repo set-default`."
        ], None
    return [], None


# --- cli ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="buildwork.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--path", default=".", help="a path inside the repository (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan", help="work out the waves, or refuse to fan out")
    p.add_argument("--goal", default="", help="the session goal, in the human's words")
    p.add_argument("--issues", help="comma-separated issue numbers, overriding the roadmap")
    p.add_argument("--runner", choices=("paseo", "subagent"), help="resolve runner=auto")
    p.add_argument("--save", action="store_true", help="record the session (only after the human approves)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("brief", help="the whole of what one worker is told")
    p.add_argument("issue", type=int)
    p.add_argument("--runner", choices=("paseo", "subagent"),
                   help="who dispatches this worker (default: the saved session, then the config)")
    p.add_argument("--branch")
    p.add_argument("--allow-hotspot", action="append", help="a hotspot this worker alone may touch")
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("qc", help="the mechanical gates against a finished branch")
    p.add_argument("issue", type=int)
    p.add_argument("--branch", help="the worker's branch, if it is not the buildwork name "
                                    "(a subagent's worktreeBranch)")
    p.add_argument("--allow-hotspot", action="append")
    p.add_argument("--no-gate", action="store_true", help="skip the domain gate, check scope and hotspots only")
    p.set_defaults(func=cmd_qc)

    p = sub.add_parser("order", help="the proposed merge order, with reasons")
    p.set_defaults(func=cmd_order)

    p = sub.add_parser("status", help="what is running, reconstructed from git and GitHub")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("init", help="write a starter config and suggest hotspots")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("doctor", help="report drift between the session, the branches and GitHub")
    p.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except gh.GhError as exc:
        fail(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
