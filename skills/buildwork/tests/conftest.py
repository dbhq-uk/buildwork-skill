"""Fixtures for the CLI harness. The harness itself, and why it is shaped as it is, is in harness.py."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness import BUILDWORK, FakeGitHub, Repo, Result, isolated_env


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def github(tmp_path: Path) -> FakeGitHub:
    return FakeGitHub(home=tmp_path / "gh")


@pytest.fixture
def repo(tmp_path: Path, home: Path) -> Repo:
    return Repo(tmp_path / "git", isolated_env(home))


@pytest.fixture
def bw(repo: Repo, github: FakeGitHub, home: Path):
    """Run buildwork.py in the fixture repository, against the fake GitHub."""
    env = {**os.environ, **isolated_env(home), **github.env()}
    env.pop("CLAUDE_SKILL_DIR", None)

    def run(*args: str, cwd: Path | None = None) -> Result:
        github.save()
        proc = subprocess.run(
            [sys.executable, str(BUILDWORK), *args], cwd=cwd or repo.root, env=env,
            capture_output=True, text=True, timeout=120,
        )
        return Result(proc.returncode, proc.stdout, proc.stderr)

    return run


@pytest.fixture
def gh_env(github: FakeGitHub, home: Path, monkeypatch):
    """The fake `gh` on PATH for in-process calls into gh.py."""
    for key, value in {**isolated_env(home), **github.env()}.items():
        monkeypatch.setenv(key, value)
    return github
