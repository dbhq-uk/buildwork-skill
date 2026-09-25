"""gh.py against real git and the fake `gh` on PATH. Nothing in gh.py is mocked."""

import pytest

import gh


# --- git ------------------------------------------------------------------

def test_repo_root_from_a_subdirectory(repo):
    (repo.root / "src" / "deep").mkdir(parents=True)
    assert gh.repo_root(repo.root / "src" / "deep") == repo.root


def test_repo_root_outside_a_repository_raises(tmp_path, repo):
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    with pytest.raises(gh.GhError):
        gh.repo_root(outside)


def test_branches_lists_local_branches_only(repo):
    repo.branch("buildwork/issue-1-a", {"a.txt": "a"})
    assert sorted(gh.branches(repo.root)) == ["buildwork/issue-1-a", "main"]


def test_worktrees_reads_linked_worktrees(repo):
    tree = repo.branch("buildwork/issue-1-a", {"a.txt": "a"}, keep_worktree=True)
    trees = {t["branch"]: t["path"] for t in gh.worktrees(repo.root)}
    assert trees["main"] == str(repo.root)
    assert trees["buildwork/issue-1-a"] == str(tree)


def test_a_detached_worktree_has_no_branch(repo, tmp_path):
    repo.git("worktree", "add", "-q", "--detach", str(tmp_path / "detached"), "main")
    detached = [t for t in gh.worktrees(repo.root) if t["path"] == str(tmp_path / "detached")]
    assert detached == [{"path": str(tmp_path / "detached"), "branch": None}]


def test_changed_files_are_the_branch_own_changes(repo):
    """Three dots: what landed on main after the branch was cut is not the branch's."""
    repo.branch("buildwork/issue-1-a", {"src/a.py": "a\n"})
    repo.on_main("someone else", {"src/other.py": "x\n"})
    assert gh.changed_files(repo.root, "main", "buildwork/issue-1-a") == ["src/a.py"]


def test_diff_size_counts_lines_added_and_removed(repo):
    repo.on_main("seed", {"src/a.py": "one\ntwo\n"})
    repo.branch("buildwork/issue-1-a", {"src/a.py": "one\nTWO\nthree\n"})
    # two added (TWO, three), one removed (two)
    assert gh.diff_size(repo.root, "main", "buildwork/issue-1-a") == 3


# --- gh -------------------------------------------------------------------

def test_open_issues_returns_open_ones_with_their_fields(repo, gh_env):
    gh_env.issue(1, "one", body="b1", labels=("bug",))
    gh_env.issue(2, "two", state="CLOSED")
    issues = gh.open_issues(repo.root)
    assert [i["number"] for i in issues] == [1]
    assert issues[0]["title"] == "one"
    assert issues[0]["body"] == "b1"
    assert issues[0]["labels"] == [{"name": "bug"}]


def test_issue_reads_one_issue(repo, gh_env):
    gh_env.issue(7, "seven", body="text")
    assert gh.issue(repo.root, 7)["title"] == "seven"


def test_a_missing_issue_raises_with_gh_own_message(repo, gh_env):
    with pytest.raises(gh.GhError, match="Could not resolve to an issue"):
        gh.issue(repo.root, 404)


def test_pulls_returns_every_state_with_its_state(repo, gh_env):
    gh_env.pull(10, "buildwork/issue-1-a")
    gh_env.pull(11, "buildwork/issue-2-b", state="MERGED")
    gh_env.pull(12, "buildwork/issue-3-c", state="CLOSED")
    got = {p["number"]: p["state"] for p in gh.pulls(repo.root)}
    assert got == {10: "OPEN", 11: "MERGED", 12: "CLOSED"}


def test_blocked_by_reads_native_links(repo, gh_env):
    gh_env.issue(1)
    gh_env.issue(2)
    gh_env.issue(3, blocked_by=(1, 2))
    assert gh.blocked_by(repo.root, 3) == [1, 2]


def test_blocked_by_prose_patterns():
    assert gh.BLOCKED_BY_PROSE.findall("Blocked by #3, and it depends on #4.") == ["3", "4"]


def test_a_missing_binary_is_a_gh_error(tmp_path):
    with pytest.raises(gh.GhError, match="not installed"):
        gh._run(["definitely-not-a-real-command-buildwork"], cwd=tmp_path)


def test_a_failing_issue_list_raises_with_gh_stderr(repo, gh_env):
    """Never `[]`: an empty list reads as "nothing to run"."""
    gh_env.fail("issue", "list")
    with pytest.raises(gh.GhError, match="Bad credentials"):
        gh.open_issues(repo.root)


def test_a_failing_pr_list_raises_with_gh_stderr(repo, gh_env):
    """Never `[]`: an empty list makes every branch look stranded."""
    gh_env.fail("pr", "list")
    with pytest.raises(gh.GhError, match="Bad credentials"):
        gh.pulls(repo.root)


def test_auth_status_raises_when_not_logged_in(repo, gh_env):
    gh.auth_status(repo.root)
    gh_env.authenticated = False
    gh_env.save()
    with pytest.raises(gh.GhError, match="gh auth login"):
        gh.auth_status(repo.root)


def test_repo_name_is_what_gh_resolves(repo, gh_env):
    assert gh.repo_name(repo.root) == "owner/repo"


def test_default_remote_is_read_from_git_config(repo):
    assert gh.remotes(repo.root) == ["origin"]
    assert not gh.default_remote_set(repo.root)
    repo.git("config", "remote.origin.gh-resolved", "base")
    assert gh.default_remote_set(repo.root)
