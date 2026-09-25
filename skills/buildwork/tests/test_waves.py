import waves


def issue(number, body="", title=""):
    return {"number": number, "title": title or f"issue {number}", "body": body}


def cands(issues, hotspots=()):
    return waves.build_candidates(issues, hotspots)


# --- declared_files -------------------------------------------------------

def test_declared_files_reads_backticked_paths():
    body = "Change `src/routes.ts` and `public/_headers` please."
    assert waves.declared_files(body) == ("src/routes.ts", "public/_headers")


def test_declared_files_ignores_bare_words_without_a_repo():
    """`gh`, `main` and `true` are not files, and treating them as such would
    make every scope check meaningless."""
    assert waves.declared_files("run `gh` on `main` when `true`") == ()


def test_bare_word_counts_when_it_exists_in_the_repo(tmp_path):
    """"Only touch `src`" names a directory. Dropping it loses the scope of a
    perfectly well-written issue."""
    (tmp_path / "src").mkdir()
    assert waves.declared_files("Only touch `src`.", tmp_path) == ("src",)


def test_bare_word_is_still_dropped_when_it_is_not_a_path(tmp_path):
    (tmp_path / "src").mkdir()
    assert waves.declared_files("run `gh` against `src`", tmp_path) == ("src",)


def test_obvious_paths_do_not_need_the_repo_to_exist(tmp_path):
    """A path with a separator or extension is unambiguous, so it counts even
    for a file the issue is asking to create."""
    assert waves.declared_files("add `src/new/thing.ts`", tmp_path) == ("src/new/thing.ts",)


def test_declared_files_deduplicates_and_keeps_order():
    body = "`a/b.py` then `c/d.py` then `a/b.py`"
    assert waves.declared_files(body) == ("a/b.py", "c/d.py")


# --- hotspots -------------------------------------------------------------

def test_hotspot_matches_exact_path():
    assert waves.hotspots_touched(("public/_headers",), ("public/_headers",)) == ("public/_headers",)


def test_hotspot_matches_directory_prefix():
    assert waves.hotspots_touched(("docs/site/copy.md",), ("docs/site",)) == ("docs/site",)


def test_similar_prefix_is_not_a_hotspot():
    """`docs/sitemap.xml` must not match the hotspot `docs/site`."""
    assert waves.hotspots_touched(("docs/sitemap.xml",), ("docs/site",)) == ()


# --- the refusals ---------------------------------------------------------

def test_single_issue_refuses_to_fan_out():
    plan = waves.plan(cands([issue(1, "`a.py`")]), {}, cap=4)
    assert plan.refusal
    assert "One issue" in plan.refusal
    assert plan.waves == []


def test_no_issues_refuses():
    plan = waves.plan([], {}, cap=4)
    assert plan.refusal
    assert "Nothing to run" in plan.refusal


def test_all_issues_touching_the_same_file_refuses():
    """Three issues on one file is one piece of work wearing three numbers."""
    plan = waves.plan(
        cands([issue(1, "`app.py`"), issue(2, "`app.py`"), issue(3, "`app.py`")]),
        {}, cap=4,
    )
    assert plan.refusal
    assert "same files" in plan.refusal


def test_partial_overlap_does_not_refuse():
    plan = waves.plan(
        cands([issue(1, "`a.py` `shared.py`"), issue(2, "`b.py`")]),
        {}, cap=4,
    )
    assert plan.refusal is None


def test_cycle_is_reported_not_smoothed_over():
    plan = waves.plan(
        cands([issue(1, "`a.py`"), issue(2, "`b.py`")]),
        {1: [2], 2: [1]}, cap=4,
    )
    assert plan.refusal
    assert "cycle" in plan.refusal
    assert plan.cycles


# --- waves ----------------------------------------------------------------

def test_independent_issues_run_together():
    plan = waves.plan(
        cands([issue(1, "`a.py`"), issue(2, "`b.py`"), issue(3, "`c.py`")]),
        {}, cap=4,
    )
    assert plan.waves == [[1, 2, 3]]
    assert plan.parallel


def test_cap_splits_a_wave():
    items = [issue(n, f"`f{n}.py`") for n in range(1, 6)]
    plan = waves.plan(cands(items), {}, cap=2)
    assert plan.waves == [[1, 2], [3, 4], [5]]


def test_dependency_orders_into_waves():
    plan = waves.plan(
        cands([issue(1, "`a.py`"), issue(2, "`b.py`"), issue(3, "`c.py`")]),
        {2: [1], 3: [1]}, cap=4,
    )
    assert plan.waves == [[1], [2, 3]]


def test_fully_chained_set_degrades_to_sequential_and_says_so():
    plan = waves.plan(
        cands([issue(1, "`a.py`"), issue(2, "`b.py`"), issue(3, "`c.py`")]),
        {2: [1], 3: [2]}, cap=4,
    )
    assert plan.waves == [[1], [2], [3]]
    assert not plan.parallel
    assert any("no parallelism" in a for a in plan.assumptions)


def test_edge_to_a_closed_issue_outside_the_set_is_ignored():
    """A blocker outside the set that is not open is closed. It holds nothing."""
    plan = waves.plan(cands([issue(1, "`a.py`"), issue(2, "`b.py`")]), {2: [99]}, cap=4)
    assert plan.waves == [[1, 2]]
    assert plan.held == {}


def test_an_open_blocker_outside_the_set_holds_its_issue():
    """Nothing in this session will close #99, so #2 cannot start in it."""
    items = [issue(1, "`a.py`"), issue(2, "`b.py`"), issue(3, "`c.py`")]
    plan = waves.plan(cands(items), {2: [99]}, cap=4, open_outside={99})
    assert plan.waves == [[1, 3]]
    assert plan.held == {2: [99]}
    assert "#2 is held: it is blocked by #99, which is open and not in this session." in plan.warnings


def test_holding_is_transitive():
    items = [issue(n, f"`{n}.py`") for n in (1, 2, 3, 4)]
    plan = waves.plan(cands(items), {2: [99], 3: [2]}, cap=4, open_outside={99})
    assert plan.waves == [[1, 4]]
    assert plan.held == {2: [99], 3: [2]}


def test_holding_can_leave_one_issue_and_that_refuses():
    items = [issue(1, "`a.py`"), issue(2, "`b.py`")]
    plan = waves.plan(cands(items), {2: [99]}, cap=4, open_outside={99})
    assert plan.refusal and "One issue (#1)" in plan.refusal
    assert plan.held == {2: [99]}


def test_roadmap_order_is_preserved_within_a_wave():
    items = [issue(7, "`g.py`"), issue(3, "`c.py`"), issue(5, "`e.py`")]
    plan = waves.plan(cands(items), {}, cap=4)
    assert plan.waves == [[7, 3, 5]]


# --- hotspot serialisation, the point of the whole thing ------------------

def test_two_issues_on_one_hotspot_do_not_share_a_wave():
    items = [issue(1, "`public/_headers` `a.py`"), issue(2, "`public/_headers` `b.py`")]
    plan = waves.plan(cands(items, ("public/_headers",)), {}, cap=4)
    assert plan.waves == [[1], [2]]
    assert any("waits a wave" in w for w in plan.warnings)


def test_a_shared_ordinary_file_also_serialises():
    """Two branches editing one file conflict whether or not anybody listed it
    as a hotspot. The hotspot list is for files that conflict even when no
    issue admits to touching them."""
    items = [issue(1, "`shared.py` `a.py`"), issue(2, "`shared.py` `b.py`")]
    plan = waves.plan(cands(items), {}, cap=4)
    assert plan.waves == [[1], [2]]
    assert any("shared.py" in w for w in plan.warnings)


def test_identical_file_sets_refuse_rather_than_serialise():
    """Serialising two issues that are the same work just runs it twice."""
    items = [issue(1, "`same.py`"), issue(2, "`same.py`")]
    plan = waves.plan(cands(items), {}, cap=4)
    assert plan.refusal
    assert "same files" in plan.refusal


def test_different_hotspots_can_share_a_wave():
    items = [issue(1, "`public/_headers`"), issue(2, "`src/routes.ts`")]
    plan = waves.plan(cands(items, ("public/_headers", "src/routes.ts")), {}, cap=4)
    assert plan.waves == [[1, 2]]


def test_a_hotspot_issue_runs_beside_an_unrelated_one():
    items = [issue(1, "`public/_headers`"), issue(2, "`src/thing.py`")]
    plan = waves.plan(cands(items, ("public/_headers",)), {}, cap=4)
    assert plan.waves == [[1, 2]]


def test_three_on_one_hotspot_becomes_three_waves():
    items = [issue(n, "`public/_headers`", ) for n in (1, 2, 3)]
    # Distinct second files so the all-same-files refusal does not fire first.
    items = [
        issue(1, "`public/_headers` `a.py`"),
        issue(2, "`public/_headers` `b.py`"),
        issue(3, "`public/_headers` `c.py`"),
    ]
    plan = waves.plan(cands(items, ("public/_headers",)), {}, cap=4)
    assert plan.waves == [[1], [2], [3]]


# --- unknown scope --------------------------------------------------------

def test_two_unknown_scope_issues_do_not_share_a_wave():
    """Nothing is known about what either touches, so running both is an unbounded bet."""
    plan = waves.plan(cands([issue(1, "no paths here"), issue(2, "none here either")]), {}, cap=4)
    assert plan.waves == [[1], [2]]
    assert any("declare no file paths" in w for w in plan.warnings)


def test_one_unknown_scope_issue_may_run_with_a_known_one():
    plan = waves.plan(cands([issue(1, "no paths"), issue(2, "`b.py`")]), {}, cap=4)
    assert plan.waves == [[1, 2]]


def test_unknown_graph_is_stated_as_an_assumption():
    plan = waves.plan(
        cands([issue(1, "`a.py`"), issue(2, "`b.py`")]), {}, cap=4, graph_is_known=False,
    )
    assert any("treated as independent" in a for a in plan.assumptions)


def test_every_issue_is_dispatched_exactly_once():
    items = [issue(n, f"`f{n}.py`") for n in range(1, 8)]
    plan = waves.plan(cands(items), {3: [1], 5: [2]}, cap=3)
    assert sorted(plan.dispatched) == list(range(1, 8))
    assert len(plan.dispatched) == len(set(plan.dispatched))
