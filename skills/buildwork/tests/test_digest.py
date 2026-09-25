"""digest.py: the brief is the whole of what a worker is told, so its words are tested exactly."""

import digest

ISSUE = {"number": 7, "title": "Add the settings route", "body": "Change `src/routes.ts`."}


def brief(**overrides):
    args = dict(
        issue=ISSUE, base="main", branch="buildwork/issue-7-add-the-settings-route",
        digest_text="", declared=("src/routes.ts",), cut_from="origin/main", runner="paseo",
    )
    args.update(overrides)
    return digest.brief(**args)


def section(text, heading):
    start = text.index(f"## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else None].rstrip("\n") + "\n"


# The bar the worker is held to, snapshot by snapshot: the gate `qc` will run,
# the hotspot this worker may change, and every one it may not.

SCOPE_WITH_A_PERMITTED_HOTSPOT = """\
## Scope

- `src/routes.ts`

**You are the one change permitted to touch `src/routes.ts` in this wave.** Other workers are explicitly barred from it.

**Do not touch these paths.** They are this repository's hotspots. Other agents are working in parallel branches right now, these conflict on every one of them, and `qc` fails a branch that changes one:

- `package-lock.json`

If your issue cannot be done without one, stop and say so rather than editing it. Leave any other shared file alone too.
"""

DONE_WITH_A_GATE = """\
## Done means

- The issue's acceptance criteria are met.
- The repository's own checks pass: run `npm test` in your worktree before
  you push. `qc` runs exactly that on your branch when you finish.
- A pull request is open, with `Closes #7` in its body.
"""


def test_a_brief_with_a_gate_and_two_hotspots_names_the_command_and_every_path():
    text = brief(
        allowed_hotspots=("src/routes.ts",), gate="npm test",
        hotspots=("src/routes.ts", "package-lock.json"),
    )
    assert section(text, "Scope") == SCOPE_WITH_A_PERMITTED_HOTSPOT
    assert section(text, "Done means") == DONE_WITH_A_GATE


def test_a_worker_sent_to_change_no_hotspot_is_shown_every_one_by_path():
    text = brief(gate="npm test", hotspots=("src/routes.ts", "package-lock.json"))
    scope = section(text, "Scope")
    assert "permitted" not in scope
    assert "- `src/routes.ts`\n- `package-lock.json`" in scope
    assert "stop and say so" in scope


def test_with_no_hotspots_configured_the_warning_stays_general():
    scope = section(brief(gate="npm test"), "Scope")
    assert "Do not touch shared configuration, route registries, lockfiles or content plans." in scope
    assert "Do not touch these paths" not in scope


def test_with_no_gate_the_brief_does_not_invent_a_command():
    done = section(brief(hotspots=("package-lock.json",)), "Done means")
    assert "- The repository's own checks pass.\n" in done
    assert "run `" not in done


def test_a_gate_with_a_backtick_in_it_stays_one_code_span():
    done = section(brief(gate="test `cat VERSION` = 1"), "Done means")
    assert "run `` test `cat VERSION` = 1 `` in your worktree" in done
