import qc


# --- scope ----------------------------------------------------------------

def test_diff_outside_declared_scope_fails():
    check = qc.scope_check(["src/a.py", "infra/secrets.tf"], ("src",))
    assert not check.passed
    assert "infra/secrets.tf" in check.detail


def test_diff_inside_declared_scope_passes():
    check = qc.scope_check(["src/a.py", "src/deep/b.py"], ("src",))
    assert check.passed


def test_exact_file_declaration_passes():
    assert qc.scope_check(["public/_headers"], ("public/_headers",)).passed


def test_prefix_lookalike_is_out_of_scope():
    """Declaring `src` must not license `srcold/`."""
    assert not qc.scope_check(["srcold/x.py"], ("src",)).passed


def test_no_declared_scope_is_unchecked_not_failed():
    """Failing every under-specified issue teaches people to declare `/` and move on."""
    check = qc.scope_check(["anything.py"], ())
    assert check.passed
    assert "not checked" in check.detail


# --- hotspots -------------------------------------------------------------

def test_unpermitted_hotspot_fails():
    check = qc.hotspot_check(["public/_headers"], ("public/_headers",))
    assert not check.passed
    assert "public/_headers" in check.detail


def test_permitted_hotspot_passes():
    """The one worker sent to change it is allowed to have changed it."""
    check = qc.hotspot_check(["public/_headers"], ("public/_headers",), allowed=("public/_headers",))
    assert check.passed


def test_no_hotspots_configured_passes():
    assert qc.hotspot_check(["anything"], ()).passed


def test_untouched_hotspot_passes():
    assert qc.hotspot_check(["src/a.py"], ("public/_headers",)).passed


# --- gate -----------------------------------------------------------------

def test_gate_passes_on_zero_exit(tmp_path):
    check = qc.run_gate("true", tmp_path)
    assert check.passed


def test_gate_fails_on_nonzero_exit(tmp_path):
    check = qc.run_gate("echo boom >&2; exit 3", tmp_path)
    assert not check.passed
    assert "exit 3" in check.detail
    assert "boom" in check.detail


def test_no_gate_passes_but_says_nothing_was_verified(tmp_path):
    check = qc.run_gate(None, tmp_path)
    assert check.passed
    assert "nothing mechanical verified" in check.detail


# --- report ---------------------------------------------------------------

def test_report_fails_if_any_check_fails(tmp_path):
    report = qc.check(
        issue=1, branch="b", changed=["out/of/scope.py"], declared=("src",),
        hotspots=(), worktree=tmp_path, gate_command="true",
    )
    assert not report.passed
    assert [c.name for c in report.failures] == ["scope"]


def test_passing_report_states_the_ceiling(tmp_path):
    """A pass is a floor. The summary must never read as a verdict on the change."""
    report = qc.check(
        issue=1, branch="b", changed=["src/a.py"], declared=("src",),
        hotspots=(), worktree=tmp_path, gate_command="true",
    )
    assert report.passed
    assert "floor, not a verdict" in report.summary()


def test_gate_is_skipped_when_there_is_no_worktree():
    report = qc.check(
        issue=1, branch="b", changed=["src/a.py"], declared=("src",),
        hotspots=(), gate_command="false",
    )
    assert [c.name for c in report.checks] == ["scope", "hotspots"]
    assert report.passed


def test_failure_summary_names_the_specific_failure():
    report = qc.check(
        issue=7, branch="buildwork/issue-7", changed=["public/_headers"], declared=(),
        hotspots=("public/_headers",),
    )
    summary = report.summary()
    assert "#7" in summary
    assert "hotspots failed" in summary
