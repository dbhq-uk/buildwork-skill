"""The CLI harness: a fake GitHub, a real git repository, and the marker for open bugs.

Most of the suite tests pure functions. The harness is for the part that is
not pure: every command meets git and GitHub, and a bug there does not crash,
it returns a confident wrong answer. So the harness uses the real thing where
it can and a faithful fake where it cannot:

- `repo` is a real git repository with a real bare remote, real branches and
  real linked worktrees. Nothing about git is mocked.
- `github` is the state behind a fake `gh` (tests/fake_gh.py) put first on
  PATH. A test says what GitHub knows, or how it fails, and the scripts call
  `gh` exactly as they would in use.
- `bw` runs `buildwork.py` as a subprocess inside `repo`, with that PATH and
  a private HOME, so a session record never lands in the real one.

`bug(N)` marks a test for an open issue. It is a strict xfail: the test fails
today, and the day the fix lands it passes, which fails the suite until the
fix removes the marker. So every linked bug has a test that fails on the
commit before its fix, and none can be fixed without somebody noticing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "scripts"
BUILDWORK = SCRIPTS / "buildwork.py"
FAKE_GH = TESTS / "fake_gh.py"

sys.path.insert(0, str(SCRIPTS))

ENABLED = 'enabled = true\nrunner = "paseo"\n'


def bug(number: int):
    """An open issue this test reproduces. Remove the marker in the fix."""
    return pytest.mark.xfail(
        strict=True,
        reason=f"open bug #{number}: this fails until the fix, and the fix removes this marker",
    )


# --- the fake GitHub ------------------------------------------------------

@dataclass
class FakeGitHub:
    """What the fake `gh` knows. Written to disk before every command runs."""

    home: Path
    repo: str = "owner/repo"
    authenticated: bool = True
    dependencies_api: bool = True
    blocked_by_field: bool = True
    issues: dict[str, dict] = field(default_factory=dict)
    pulls: list[dict] = field(default_factory=list)
    blocked_by: dict[str, list[dict]] = field(default_factory=dict)
    failures: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.bin = self.home / "bin"
        self.bin.mkdir(parents=True, exist_ok=True)
        self.state_path = self.home / "github.json"
        self.log_path = self.home / "gh-calls.jsonl"
        shim = self.bin / "gh"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_GH}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
        self.save()

    def issue(self, number: int, title: str = "", body: str = "", labels=(),
              state: str = "OPEN", author: str = "maintainer", blocked_by=()) -> dict:
        raw = {
            "number": number, "title": title or f"issue {number}", "body": body,
            "labels": list(labels), "state": state, "author": author,
        }
        self.issues[str(number)] = raw
        if blocked_by:
            self.block(number, *blocked_by)
        self.save()
        return raw

    def block(self, number: int, *blockers) -> None:
        """Record `blocked by` links. An int is a local issue; "owner/other#12" is another repository's."""
        for ref in blockers:
            if isinstance(ref, int):
                entry = {"repo": self.repo, "number": ref}
            elif isinstance(ref, str):
                repo, _, n = ref.partition("#")
                entry = {"repo": repo or self.repo, "number": int(n)}
            else:
                entry = dict(ref)
            self.blocked_by.setdefault(str(number), []).append(entry)
        self.save()

    def pull(self, number: int, head: str, state: str = "OPEN", title: str = "",
             body: str = "", draft: bool = False) -> dict:
        raw = {
            "number": number, "headRefName": head, "state": state,
            "title": title or f"pull {number}", "body": body, "isDraft": draft,
        }
        self.pulls = [p for p in self.pulls if p["number"] != number] + [raw]
        self.save()
        return raw

    def fail(self, *tokens: str, stderr: str = "HTTP 401: Bad credentials (https://api.github.com/graphql)",
             code: int = 1) -> None:
        """Make any call whose arguments contain these tokens, in order, fail like gh does."""
        self.failures.append({"tokens": list(tokens), "stderr": stderr, "code": code})
        self.save()

    def save(self) -> None:
        state = {
            "repo": self.repo,
            "authenticated": self.authenticated,
            "dependencies_api": self.dependencies_api,
            "blocked_by_field": self.blocked_by_field,
            "issues": self.issues,
            "pulls": self.pulls,
            "blocked_by": self.blocked_by,
            "failures": self.failures,
        }
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def env(self) -> dict[str, str]:
        return {
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_GH_STATE": str(self.state_path),
            "FAKE_GH_LOG": str(self.log_path),
        }

    def calls(self) -> list[list[str]]:
        if not self.log_path.is_file():
            return []
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]


# --- the real git repository ----------------------------------------------

def isolated_env(home: Path) -> dict[str, str]:
    """No global or system git config, so a signing or hook setting on the host cannot leak in."""
    home.mkdir(parents=True, exist_ok=True)
    return {
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_TERMINAL_PROMPT": "0",
    }


class Repo:
    """A real working clone of a real bare remote, with `main` pushed.

    Branches are made in a linked worktree and, unless the test wants the
    worktree kept, the worktree is removed afterwards and the branch stays.
    That is exactly the trace a finished or dead agent leaves.
    """

    def __init__(self, base: Path, env: dict[str, str]):
        self.base = base
        self.env = {**os.environ, **env}
        self.remote = base / "remote.git"
        self.root = base / "work"
        self.trees = base / "trees"
        self.trees.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "--bare", "-b", "main", str(self.remote), cwd=base)
        self.git("init", "-q", "-b", "main", str(self.root), cwd=base)
        self.git("remote", "add", "origin", str(self.remote))
        self.write("README.md", "# fixture\n")
        self.write(".github/buildwork.toml", ENABLED)
        self.commit("initial")
        self.git("push", "-q", "-u", "origin", "main")

    def git(self, *args: str, cwd: Path | None = None) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=cwd or self.root, env=self.env,
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr}")
        return proc.stdout

    def write(self, rel: str, text: str, root: Path | None = None) -> None:
        path = (root or self.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message: str, files: dict[str, str] | None = None, cwd: Path | None = None) -> None:
        for rel, text in (files or {}).items():
            self.write(rel, text, cwd)
        self.git("add", "-A", cwd=cwd)
        self.git("commit", "-q", "--allow-empty", "-m", message, cwd=cwd)

    def on_main(self, message: str, files: dict[str, str], push: bool = True) -> None:
        """Commit to main in the working clone, and push it unless told not to."""
        self.commit(message, files)
        if push:
            self.git("push", "-q", "origin", "main")

    def configure(self, text: str) -> None:
        """Replace .github/buildwork.toml on main. `text` is the whole file."""
        self.on_main("configure buildwork", {".github/buildwork.toml": text})

    def branch(self, name: str, files: dict[str, str] | None = None, keep_worktree: bool = False,
               base: str = "main") -> Path | None:
        """Cut `name` from `base`, commit `files` on it, and optionally leave a worktree on it."""
        tree = self.trees / name.replace("/", "-")
        self.git("worktree", "add", "-q", "-b", name, str(tree), base)
        if files:
            self.commit(f"work on {name}", files, cwd=tree)
        if keep_worktree:
            return tree
        self.git("worktree", "remove", "--force", str(tree))
        return None

    def merge_on_github(self, branch: str) -> None:
        """Squash-merge `branch` into the remote's main, as the GitHub button does.

        Local main is left where it was, as it is after a real merge until
        somebody fetches, and the local branch is left in place.
        """
        tree = self.trees / f"merge-{branch.replace('/', '-')}"
        self.git("fetch", "-q", "origin")
        self.git("worktree", "add", "-q", "--detach", str(tree), "origin/main")
        self.git("merge", "-q", "--squash", branch, cwd=tree)
        self.git("commit", "-q", "-m", f"{branch} (squash)", cwd=tree)
        self.git("push", "-q", "origin", "HEAD:main", cwd=tree)
        self.git("worktree", "remove", "--force", str(tree))

    def worktree(self, path: Path, branch: str) -> Path:
        """A linked worktree on an existing branch, as an orchestrator's own checkout might be."""
        self.git("worktree", "add", "-q", str(path), branch)
        return path


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def text(self) -> str:
        return self.out + self.err

    def json(self):
        return json.loads(self.out)
