"""SKILL.md's commands must run after Claude Code has substituted them.

Claude Code replaces `${CLAUDE_SKILL_DIR}`, braced, and nothing else. The
unbraced `$CLAUDE_SKILL_DIR` reaches the shell as it is, the shell has no such
variable, and the command becomes `python3 "/scripts/buildwork.py"`. These
tests do the substitution the host does and then run what is left, so a
command that only works under Codex's installer cannot ship again.
"""

import os
import re
import subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_MD = SKILL_DIR / "SKILL.md"

FENCE = re.compile(r"```bash\n(.*?)```", re.S)


def commands() -> list[str]:
    text = SKILL_MD.read_text(encoding="utf-8")
    lines = []
    for block in FENCE.findall(text):
        lines += [line.strip() for line in block.splitlines() if line.strip()]
    return lines


def substitute(command: str) -> str:
    """What Claude Code does to a skill before the model sees it: the braced form only."""
    return command.replace("${CLAUDE_SKILL_DIR}", str(SKILL_DIR))


def test_skill_md_has_commands():
    assert any("buildwork.py" in c for c in commands())


def test_every_command_names_a_script_that_exists_after_substitution():
    for command in commands():
        match = re.search(r'python3 "([^"]+)"', substitute(command))
        assert match, f"not a python3 command: {command}"
        assert Path(match.group(1)).is_file(), (
            f"after substitution this runs {match.group(1)}, which does not exist: {command}"
        )


def test_every_plan_command_names_its_runner():
    """With runner = "auto", plan refuses without --runner, and a guessed runner sets the wrong cap."""
    plans = [c for c in commands() if re.search(r"buildwork\.py\" plan\b", c)]
    assert plans
    for command in plans:
        assert "--runner" in command, command


def test_no_unbraced_skill_dir_anywhere_in_the_skill():
    for path in SKILL_DIR.rglob("*.md"):
        assert "$CLAUDE_SKILL_DIR" not in path.read_text(encoding="utf-8"), path


def test_doctor_runs_as_written(tmp_path):
    """The first command SKILL.md tells the agent to run, run the way the host runs it."""
    doctor = next(c for c in commands() if c.endswith(" doctor"))
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_SKILL_DIR"}
    proc = subprocess.run(
        ["bash", "-c", substitute(doctor)], cwd=tmp_path, env=env,
        capture_output=True, text=True, timeout=60,
    )
    # No config in a fresh repository, so doctor stops at the opt-in gate. That
    # message proves the script was found and ran.
    assert "can't open file" not in proc.stderr
    assert "buildwork is opt-in per repository" in proc.stderr


def test_the_skill_name_matches_its_folder():
    """A name that differs from its folder installs under one name and is invoked under another."""
    front = SKILL_MD.read_text(encoding="utf-8").split("---")[1]
    name = re.search(r"^name:\s*(.+?)\s*$", front, re.M).group(1)
    assert name == SKILL_DIR.name


def test_no_trigger_would_fire_on_a_question_about_system_processes():
    description = SKILL_MD.read_text(encoding="utf-8").split("---")[1]
    assert "\"what's running\"" not in description
