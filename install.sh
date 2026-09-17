#!/bin/bash
# Install buildwork into ~/.claude/skills/ as a live symlink.
#
# SKILL.md references its scripts via ${CLAUDE_SKILL_DIR}, which Claude Code
# substitutes to the skill's own directory for personal, project and plugin
# installs alike. So this script symlinks the whole skill directory - every
# edit (scripts AND SKILL.md) is immediately live, with no per-file rewrite.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_ROOT="$HOME/.claude/skills"

echo "=== buildwork installer (Claude Code) ==="
echo

# --- Dependencies ---
MISSING=""
command -v git >/dev/null 2>&1 || MISSING="$MISSING git"
command -v gh >/dev/null 2>&1  || MISSING="$MISSING gh"

if ! command -v python3 >/dev/null 2>&1; then
  MISSING="$MISSING python3"
else
  # tomllib landed in 3.11, and the config is TOML precisely so that no YAML
  # package is needed. An older Python fails at the first config read rather
  # than at install, which is a confusing place to find out.
  if ! python3 -c 'import tomllib' >/dev/null 2>&1; then
    echo "Python $(python3 -V 2>&1 | cut -d' ' -f2) has no tomllib. buildwork needs 3.11 or later."
    echo
  fi
fi

if [ -n "$MISSING" ]; then
  echo "Missing:$MISSING"
  echo "buildwork needs git and an authenticated gh. Install those, then re-run."
  echo
else
  echo "Dependencies OK."
  if ! gh auth status >/dev/null 2>&1; then
    echo "gh is installed but not authenticated. Run: gh auth login"
  fi
fi
echo

# --- Install as a full-directory symlink ---
mkdir -p "$SKILLS_ROOT"
src="$SCRIPT_DIR/skills/buildwork"
target="$SKILLS_ROOT/buildwork"

echo "Installing 'buildwork' -> $target"
rm -rf "$target"            # replace any prior copy or partial-symlink install
ln -sfn "$src" "$target"    # whole-directory symlink; ${CLAUDE_SKILL_DIR} resolves it

echo
echo "Installed as a directory symlink - all edits are live."
echo
echo "buildwork does nothing until a repository opts in. In a repo you want it on:"
echo "  python3 $target/scripts/buildwork.py init"
echo "then set enabled = true in .github/buildwork.toml."
echo
echo "Then try: 'work through the backlog' or 'what's running'"
