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
        pulls=[{"headRefName": "buildwork/issue-1-a", "number": 50, "url": "u"}],
    )
    assert items[0].status == state.READY
    assert items[0].pr == 50


def test_worktree_and_no_pull_request_means_running():
    items = state.reconstruct(
        wave_issues=[1],
        all_branches=["buildwork/issue-1-a"],
        worktrees=[{"branch": "buildwork/issue-1-a", "path": "/tmp/wt"}],
        pulls=[],
    )
    assert items[0].status == state.RUNNING
    assert items[0].worktree == "/tmp/wt"


def test_branch_with_no_worktree_and_no_pull_request_is_stalled():
    """The agent is gone and nothing collected the work. This is the state that
    silently loses money, so it must have a name."""
    items = state.reconstruct(
        wave_issues=[1], all_branches=["buildwork/issue-1-a"], worktrees=[], pulls=[],
    )
    assert items[0].status == state.STALLED


def test_issue_with_no_branch_is_not_started():
    items = state.reconstruct(wave_issues=[1], all_branches=["main"], worktrees=[], pulls=[])
    assert items[0].status == state.NO_BRANCH
    assert items[0].branch is None


def test_branch_outside_the_session_is_surfaced_as_an_orphan():
    items = state.reconstruct(
        wave_issues=[1],
        all_branches=["buildwork/issue-1-a", "buildwork/issue-99-old"],
        worktrees=[], pulls=[],
    )
    orphans = [i for i in items if i.status == state.UNKNOWN_BRANCH]
    assert [o.issue for o in orphans] == [99]


def test_orphan_with_a_pull_request_is_ready_not_orphaned():
    items = state.reconstruct(
        wave_issues=[],
        all_branches=["buildwork/issue-99-old"],
        worktrees=[],
        pulls=[{"headRefName": "buildwork/issue-99-old", "number": 7, "url": "u"}],
    )
    assert items[0].status == state.READY


def test_reconstruction_needs_no_session_record():
    """Resume after a crash: nothing but branches and pull requests exist."""
    items = state.reconstruct(
        wave_issues=[],
        all_branches=["buildwork/issue-5-x"],
        worktrees=[{"branch": "buildwork/issue-5-x", "path": "/tmp/w"}],
        pulls=[],
    )
    assert [i.issue for i in items] == [5]


def test_summary_puts_what_needs_you_first():
    items = state.reconstruct(
        wave_issues=[1, 2, 3],
        all_branches=["buildwork/issue-1-a", "buildwork/issue-2-b"],
        worktrees=[{"branch": "buildwork/issue-2-b", "path": "/tmp/w"}],
        pulls=[{"headRefName": "buildwork/issue-1-a", "number": 9, "url": "u"}],
    )
    text = state.summarise(items)
    assert text.index("Waiting on you") < text.index("Running")
    assert text.index("Running") < text.index("Not started")


def test_summary_of_nothing_says_nothing_is_in_flight():
    assert "Nothing in flight" in state.summarise([])


def test_merged_pull_request_is_done_not_stalled():
    """After a squash merge the local branch is still there. That is finished work, not a dead agent."""
    items = state.reconstruct(
        wave_issues=[1],
        all_branches=["buildwork/issue-1-a"],
        worktrees=[],
        pulls=[{"headRefName": "buildwork/issue-1-a", "number": 50, "url": "u", "state": "MERGED"}],
    )
    assert items[0].status == state.MERGED
    assert items[0].pr == 50


def test_closed_pull_request_is_done_not_stalled():
    items = state.reconstruct(
        wave_issues=[1],
        all_branches=["buildwork/issue-1-a"],
        worktrees=[{"branch": "buildwork/issue-1-a", "path": "/tmp/w"}],
        pulls=[{"headRefName": "buildwork/issue-1-a", "number": 50, "url": "u", "state": "CLOSED"}],
    )
    assert items[0].status == state.CLOSED


def test_an_open_pull_request_outranks_an_older_closed_one_on_the_same_branch():
    pulls = [
        {"headRefName": "b", "number": 3, "state": "CLOSED"},
        {"headRefName": "b", "number": 9, "state": "OPEN"},
        {"headRefName": "c", "number": 4, "state": "CLOSED"},
        {"headRefName": "c", "number": 5, "state": "MERGED"},
    ]
    best = state.pulls_by_branch(pulls)
    assert best["b"]["number"] == 9
    assert best["c"]["number"] == 5


def test_a_merged_orphan_is_merged_not_orphaned():
    items = state.reconstruct(
        wave_issues=[],
        all_branches=["buildwork/issue-99-old"],
        worktrees=[],
        pulls=[{"headRefName": "buildwork/issue-99-old", "number": 7, "url": "u", "state": "MERGED"}],
    )
    assert items[0].status == state.MERGED


def test_summary_puts_finished_work_last():
    items = state.reconstruct(
        wave_issues=[1, 2],
        all_branches=["buildwork/issue-1-a", "buildwork/issue-2-b"],
        worktrees=[],
        pulls=[
            {"headRefName": "buildwork/issue-1-a", "number": 9, "url": "u", "state": "MERGED"},
            {"headRefName": "buildwork/issue-2-b", "number": 10, "url": "u", "state": "OPEN"},
        ],
    )
    text = state.summarise(items)
    assert text.index("Waiting on you") < text.index("Merged")
    assert "Stalled" not in text
