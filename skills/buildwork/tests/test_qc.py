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


# --- secrets --------------------------------------------------------------
# Every token here is built at run time, so no credential-shaped literal is in
# the source for a scanner, GitHub's included, to trip on.

def _tokens():
    return {
        "a private key": "-----BEGIN " + "OPENSSH PRIVATE KEY-----",
        "an AWS access key id": "AKIA" + "ABCDEFGHIJKLMNOP",
        "a GitHub token": "gh" + "p_" + "a1B2" * 9,
        "a Slack token": "xo" + "xb-" + "1234567890-abcdef",
        "a Google API key": "AI" + "za" + "x" * 35,
        "a Stripe live key": "sk" + "_live_" + "a1" * 12,
        "an Anthropic API key": "sk-" + "ant-" + "a1_" * 8,
        "an OpenAI project key": "sk-" + "proj-" + "a1-" * 8,
    }


def test_every_known_credential_shape_fails_the_branch():
    for name, token in _tokens().items():
        check = qc.secret_check([("src/config.py", f'TOKEN = "{token}"')])
        assert not check.passed, name
        assert f"{name} in src/config.py" in check.detail
        assert token not in check.detail, "the value itself is never printed"
        assert "rotate" in check.detail


def test_hashes_and_fixtures_are_not_credentials():
    lines = [
        ("lock.json", '"integrity": "sha512-' + "A" * 86 + '=="'),
        ("src/a.py", "commit = '" + "0123456789abcdef" * 2 + "5678abcd'"),
        ("docs/x.md", "Set GITHUB_TOKEN in your environment, never in the repository."),
        ("src/b.py", "key = os.environ['AWS_ACCESS_KEY_ID']"),
    ]
    assert qc.secret_check(lines).passed


def test_one_credential_in_many_files_names_each_file_once():
    token = _tokens()["a GitHub token"]
    check = qc.secret_check([("a.env", token), ("a.env", token), ("b.env", token)])
    assert check.detail.count("in a.env") == 1 and "in b.env" in check.detail


def test_the_secret_check_runs_only_when_the_added_lines_are_given():
    names = [c.name for c in qc.check(1, "b", [], (), ()).checks]
    assert "secrets" not in names
    names = [c.name for c in qc.check(1, "b", [], (), (), added=[]).checks]
    assert "secrets" in names
