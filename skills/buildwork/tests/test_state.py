import state


def test_branch_name_round_trips():
    branch = state.branch_for(143, "The GitHub metadata register has drifted")
    assert branch.startswith("buildwork/issue-143-")
    assert state.issue_from_branch(branch) == 143


def test_branch_name_survives_an_empty_title():
    branch = state.branch_for(7, "")
    assert branch == "buildwork/issue-7"
    assert state.issue_from_branch(branch) == 7


def test_branch_name_is_slugged_and_bounded():
    branch = state.branch_for(1, "Fix: the thing!! (urgently) " + "x" * 200)
    assert " " not in branch and "!" not in branch and "(" not in branch
    assert len(branch) < 80
    assert state.issue_from_branch(branch) == 1


def test_unrelated_branches_are_not_buildwork_branches():
    for name in ("main", "feature/x", "buildwork", "buildwork/other"):
        assert state.issue_from_branch(name) is None


def test_pull_request_means_ready():
    items = state.reconstruct(
        wave_issues=[1],
        all_branches=["main", "buildwork/issue-1-a"],
        worktrees=[],
        open_pulls=[{"headRefName": "buildwork/issue-1-a", "number": 50, "url": "u"}],
    )
    assert items[0].status == state.READY
    assert items[0].pr == 50


def test_worktree_and_no_pull_request_means_running():
    items = state.reconstruct(
        wave_issues=[1],
        all_branches=["buildwork/issue-1-a"],
        worktrees=[{"branch": "buildwork/issue-1-a", "path": "/tmp/wt"}],
        open_pulls=[],
    )
    assert items[0].status == state.RUNNING
    assert items[0].worktree == "/tmp/wt"


def test_branch_with_no_worktree_and_no_pull_request_is_stalled():
    """The agent is gone and nothing collected the work. This is the state that
    silently loses money, so it must have a name."""
    items = state.reconstruct(
        wave_issues=[1], all_branches=["buildwork/issue-1-a"], worktrees=[], open_pulls=[],
    )
    assert items[0].status == state.STALLED


def test_issue_with_no_branch_is_not_started():
    items = state.reconstruct(wave_issues=[1], all_branches=["main"], worktrees=[], open_pulls=[])
    assert items[0].status == state.NO_BRANCH
    assert items[0].branch is None


def test_branch_outside_the_session_is_surfaced_as_an_orphan():
    items = state.reconstruct(
        wave_issues=[1],
        all_branches=["buildwork/issue-1-a", "buildwork/issue-99-old"],
        worktrees=[], open_pulls=[],
    )
    orphans = [i for i in items if i.status == state.UNKNOWN_BRANCH]
    assert [o.issue for o in orphans] == [99]


def test_orphan_with_a_pull_request_is_ready_not_orphaned():
    items = state.reconstruct(
        wave_issues=[],
        all_branches=["buildwork/issue-99-old"],
        worktrees=[],
        open_pulls=[{"headRefName": "buildwork/issue-99-old", "number": 7, "url": "u"}],
    )
    assert items[0].status == state.READY


def test_reconstruction_needs_no_session_record():
    """Resume after a crash: nothing but branches and pull requests exist."""
    items = state.reconstruct(
        wave_issues=[],
        all_branches=["buildwork/issue-5-x"],
        worktrees=[{"branch": "buildwork/issue-5-x", "path": "/tmp/w"}],
        open_pulls=[],
    )
    assert [i.issue for i in items] == [5]


def test_summary_puts_what_needs_you_first():
    items = state.reconstruct(
        wave_issues=[1, 2, 3],
        all_branches=["buildwork/issue-1-a", "buildwork/issue-2-b"],
        worktrees=[{"branch": "buildwork/issue-2-b", "path": "/tmp/w"}],
        open_pulls=[{"headRefName": "buildwork/issue-1-a", "number": 9, "url": "u"}],
    )
    text = state.summarise(items)
    assert text.index("Waiting on you") < text.index("Running")
    assert text.index("Running") < text.index("Not started")


def test_summary_of_nothing_says_nothing_is_in_flight():
    assert "Nothing in flight" in state.summarise([])
