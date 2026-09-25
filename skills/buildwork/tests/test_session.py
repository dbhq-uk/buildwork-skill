"""session.py: the one thing buildwork writes outside the repository."""

import json
import stat
import time

import pytest

import session


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    path = tmp_path / "home" / ".dbhq" / "buildwork"
    monkeypatch.setattr(session, "STATE_DIR", path)
    return path


def test_save_and_load_round_trip(state_dir, tmp_path):
    saved = session.Session(repo="owner/repo", goal="ship the thing", issues=[1, 2], waves=[[1, 2]], runner="paseo")
    session.save("owner/repo", saved)
    loaded = session.load("owner/repo")
    assert loaded == saved


def test_nothing_saved_loads_as_none(state_dir, tmp_path):
    assert session.load("owner/repo") is None


def test_record_is_private(state_dir, tmp_path):
    path = session.save("owner/repo", session.Session(repo="owner/repo", goal="g"))
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_the_record_is_keyed_on_owner_and_repo(state_dir):
    """Not the folder name: two repositories called `repo` under two owners are two records."""
    session.save("owner/repo", session.Session(repo="owner/repo", goal="mine"))
    session.save("other/repo", session.Session(repo="other/repo", goal="theirs"))
    assert session.load("owner/repo").goal == "mine"
    assert session.load("other/repo").goal == "theirs"
    assert (state_dir / "owner" / "repo.json").is_file()


def test_the_key_ignores_case_as_github_does(state_dir):
    session.save("Owner/Repo", session.Session(repo="Owner/Repo", goal="g"))
    assert session.load("owner/repo").goal == "g"


@pytest.mark.parametrize("bad", ["", "repo", "owner/", "/repo", "owner/a/b", "../repo", "owner/.."])
def test_a_key_that_is_not_owner_and_repo_is_refused(state_dir, bad):
    with pytest.raises(ValueError):
        session.save(bad, session.Session(repo=bad, goal="g"))


def test_a_corrupt_record_is_treated_as_none(state_dir, tmp_path):
    path = session.save("owner/repo", session.Session(repo="owner/repo", goal="g"))
    path.write_text("{not json", encoding="utf-8")
    assert session.load("owner/repo") is None


def test_unknown_keys_are_ignored(state_dir, tmp_path):
    """A record written by a newer version must still load."""
    path = session.save("owner/repo", session.Session(repo="owner/repo", goal="g"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["something_new"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    assert session.load("owner/repo").goal == "g"


def test_clear_removes_the_record(state_dir, tmp_path):
    session.save("owner/repo", session.Session(repo="owner/repo", goal="g"))
    session.clear("owner/repo")
    assert session.load("owner/repo") is None
    session.clear("owner/repo")  # clearing nothing is not an error


def test_a_record_older_than_three_days_is_stale():
    fresh = session.Session(repo="r", goal="g")
    old = session.Session(repo="r", goal="g", started=time.time() - session.STALE_AFTER - 60)
    assert not fresh.stale
    assert old.stale


@pytest.mark.parametrize("age,text", [
    (5 * 60, "5 minutes ago"),
    (5 * 3600, "5 hours ago"),
    (4 * 24 * 3600, "4 days ago"),
])
def test_age_text(age, text):
    assert session.Session(repo="r", goal="g", started=time.time() - age - 1).age_text() == text


def test_hotspot_permission_round_trips(state_dir, tmp_path):
    saved = session.Session(repo="owner/repo", goal="g", issues=[1, 2], hotspots={"1": ["public/_headers"]})
    session.save("owner/repo", saved)
    loaded = session.load("owner/repo")
    assert loaded.allowed_hotspots(1) == ("public/_headers",)
    assert loaded.allowed_hotspots(2) == ()


def test_a_record_from_before_hotspots_were_saved_still_loads(state_dir, tmp_path):
    path = session.save("owner/repo", session.Session(repo="owner/repo", goal="g"))
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["hotspots"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert session.load("owner/repo").allowed_hotspots(1) == ()
