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
    root = tmp_path / "repo"
    saved = session.Session(repo="repo", goal="ship the thing", issues=[1, 2], waves=[[1, 2]], runner="paseo")
    session.save(root, saved)
    loaded = session.load(root)
    assert loaded == saved


def test_nothing_saved_loads_as_none(state_dir, tmp_path):
    assert session.load(tmp_path / "repo") is None


def test_record_is_private(state_dir, tmp_path):
    path = session.save(tmp_path / "repo", session.Session(repo="repo", goal="g"))
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_corrupt_record_is_treated_as_none(state_dir, tmp_path):
    path = session.save(tmp_path / "repo", session.Session(repo="repo", goal="g"))
    path.write_text("{not json", encoding="utf-8")
    assert session.load(tmp_path / "repo") is None


def test_unknown_keys_are_ignored(state_dir, tmp_path):
    """A record written by a newer version must still load."""
    path = session.save(tmp_path / "repo", session.Session(repo="repo", goal="g"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["something_new"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    assert session.load(tmp_path / "repo").goal == "g"


def test_clear_removes_the_record(state_dir, tmp_path):
    session.save(tmp_path / "repo", session.Session(repo="repo", goal="g"))
    session.clear(tmp_path / "repo")
    assert session.load(tmp_path / "repo") is None
    session.clear(tmp_path / "repo")  # clearing nothing is not an error


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
