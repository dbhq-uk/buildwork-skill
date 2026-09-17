#!/bin/bash
# Install buildwork into ~/.codex/skills/ for Codex.
#
# Codex does not substitute ${CLAUDE_SKILL_DIR}, so this script rewrites that
# variable to the installed Codex path and symlinks the supporting directories
# (edits to those stay live). Re-run after editing SKILL.md.
#
# There is no build step: buildwork is Python standard library and shells out
# to git and gh.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_ROOT="$HOME/.codex/skills"

echo "=== buildwork installer (Codex) ==="
echo

# --- Dependencies ---
MISSING=""
command -v git >/dev/null 2>&1 || MISSING="$MISSING git"
command -v gh >/dev/null 2>&1  || MISSING="$MISSING gh"

if ! command -v python3 >/dev/null 2>&1; then
  MISSING="$MISSING python3"
elif ! python3 -c 'import tomllib' >/dev/null 2>&1; then
  echo "Python $(python3 -V 2>&1 | cut -d' ' -f2) has no tomllib. buildwork needs 3.11 or later."
  echo
fi

if [ -n "$MISSING" ]; then
  echo "Missing:$MISSING"
  echo "buildwork needs git and an authenticated gh. Install those, then re-run."
  echo
else
  echo "Dependencies OK."
fi
echo

src="$SCRIPT_DIR/skills/buildwork"
target="$SKILLS_ROOT/buildwork"

mkdir -p "$target"
echo "Installing 'buildwork' -> $target"

# Clear what a previous install left before linking what this one needs.
# Without this, an entry since renamed or deleted upstream survives as a
# symlink to a path that no longer exists - and a dangling link fails more
# confusingly than a missing file, because it looks installed. Only symlinks
# are removed, so a real SKILL.md is never at risk.
find "$target" -mindepth 1 -maxdepth 1 -type l -exec rm -f {} +

for sub in references scripts; do
  [ -d "$src/$sub" ] && ln -sfn "$src/$sub" "$target/$sub"
done

sed "s#\${CLAUDE_SKILL_DIR}#$target#g; s#\$CLAUDE_SKILL_DIR#$target#g" "$src/SKILL.md" > "$target/SKILL.md"

echo
echo "Installed for Codex. Re-run after editing SKILL.md - that file is rewritten"
echo "at install time rather than symlinked, so its edits are not live."
echo
echo "buildwork does nothing until a repository opts in:"
echo "  python3 $target/scripts/buildwork.py init"
echo "then set enabled = true in .github/buildwork.toml."
