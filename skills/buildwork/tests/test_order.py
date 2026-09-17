import order


def ready(issue, pr=1, hotspots=(), blocked_by=(), diff_size=10, qc_passed=True):
    return order.Ready(
        issue=issue, branch=f"buildwork/issue-{issue}", pr=pr, hotspots=hotspots,
        blocked_by=blocked_by, diff_size=diff_size, qc_passed=qc_passed,
    )


def numbers(positions):
    return [p.item.issue for p in positions]


def test_hotspot_pull_request_goes_first():
    positions, _ = order.propose([
        ready(1, diff_size=5),
        ready(2, hotspots=("public/_headers",), diff_size=500),
    ])
    assert numbers(positions)[0] == 2
    assert "rebases over it once" in positions[0].reason


def test_dependency_order_is_respected():
    positions, _ = order.propose([ready(2, blocked_by=(1,)), ready(1)])
    assert numbers(positions) == [1, 2]
    assert "blocked by #1" in positions[1].reason


def test_smallest_diff_first_among_independents():
    positions, _ = order.propose([ready(1, diff_size=300), ready(2, diff_size=10), ready(3, diff_size=80)])
    assert numbers(positions) == [2, 3, 1]


def test_hotspot_beats_a_smaller_diff():
    positions, _ = order.propose([ready(1, diff_size=1), ready(2, hotspots=("x",), diff_size=900)])
    assert numbers(positions) == [2, 1]


def test_dependency_beats_diff_size():
    """A tiny diff that is blocked still waits for its blocker."""
    positions, _ = order.propose([ready(2, blocked_by=(1,), diff_size=1), ready(1, diff_size=900)])
    assert numbers(positions) == [1, 2]


def test_blocker_outside_the_set_does_not_hold_it_back():
    positions, _ = order.propose([ready(1, blocked_by=(99,))])
    assert numbers(positions) == [1]


def test_failed_qc_is_held_back_and_named():
    positions, notes = order.propose([ready(1), ready(2, qc_passed=False)])
    assert numbers(positions) == [1]
    assert any("#2" in n and "QC not passed" in n for n in notes)


def test_branch_without_a_pull_request_is_flagged():
    positions, notes = order.propose([ready(1, pr=None)])
    assert numbers(positions) == [1]
    assert any("No pull request yet" in n for n in notes)


def test_cycle_among_ready_branches_is_reported():
    positions, notes = order.propose([ready(1, blocked_by=(2,)), ready(2, blocked_by=(1,))])
    assert len(positions) == 2
    assert any("Circular dependency" in n for n in notes)


def test_every_ready_item_is_placed_exactly_once():
    items = [ready(n, diff_size=n * 10) for n in range(1, 7)]
    positions, _ = order.propose(items)
    assert sorted(numbers(positions)) == list(range(1, 7))


def test_render_says_buildwork_does_not_merge():
    positions, notes = order.propose([ready(1)])
    text = order.render(positions, notes)
    assert "does not merge" in text
    assert "closes #1" in text


def test_render_lists_the_branch_when_there_is_no_pr():
    positions, notes = order.propose([ready(1, pr=None)])
    assert "branch buildwork/issue-1" in order.render(positions, notes)
