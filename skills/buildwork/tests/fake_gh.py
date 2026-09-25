"""A fake `gh`, put first on PATH by the CLI tests.

It answers the subset of `gh` that buildwork calls, from a JSON file the test
writes (see `FakeGitHub` in conftest.py). Nothing here touches a network or a
token, so a test can make GitHub say anything, including fail.

The shapes follow what gh 2.100 actually prints, because a fake that is kinder
than the real thing is how the bugs this harness exists for got past a green
suite:

- a failed call exits non-zero and writes gh's own message to stderr
- `gh api` on a 404 prints the JSON error body to stdout as well as failing
- `gh api` without `--paginate` returns one page of 30, like the REST API
- `gh api --paginate` prints each page back to back, which is not one JSON
  document unless `--slurp` is also passed
- `gh pr list --state closed` includes merged pull requests
- an unknown `--json` field is an error, not an empty value
- `blockedBy` is `{"nodes": [...], "totalCount": N}`, first 50 only

A command this fake does not model exits 1 with "fake gh: unsupported". That
is deliberate: a fix that starts calling something new has to teach the fake
what GitHub says, rather than silently getting nothing back.

Every call is appended to FAKE_GH_LOG, one JSON array per line, so a test can
assert what was asked as well as what was answered.
"""

from __future__ import annotations

import json
import os
import sys
from urllib.parse import parse_qs, urlsplit

PAGE = 30          # the REST API's default per_page
BLOCKED_BY_MAX = 50  # gh's GraphQL query asks for blockedBy(first:50)

ISSUE_FIELDS = {
    "number", "title", "body", "labels", "url", "state", "author", "blockedBy",
    "createdAt", "updatedAt", "assignees",
}
PR_FIELDS = {
    "number", "title", "headRefName", "baseRefName", "url", "isDraft", "body",
    "state", "mergedAt", "closedAt", "author",
}
REPO_FIELDS = {"nameWithOwner", "name", "owner", "url", "defaultBranchRef"}


def load() -> dict:
    with open(os.environ["FAKE_GH_STATE"], encoding="utf-8") as fh:
        return json.load(fh)


def log(argv: list[str]) -> None:
    path = os.environ.get("FAKE_GH_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(argv) + "\n")


def die(message: str, code: int = 1, stdout: str = "") -> None:
    if stdout:
        sys.stdout.write(stdout)
    sys.stderr.write(message.rstrip("\n") + "\n")
    raise SystemExit(code)


def pop_flag(args: list[str], *names: str, default=None):
    """Remove `--name value` or `--name=value` from args and return the value."""
    for i, arg in enumerate(args):
        for name in names:
            if arg == name and i + 1 < len(args):
                value = args[i + 1]
                del args[i:i + 2]
                return value
            if arg.startswith(name + "="):
                del args[i]
                return arg.split("=", 1)[1]
    return default


def pop_switch(args: list[str], name: str) -> bool:
    if name in args:
        args.remove(name)
        return True
    return False


def contains_in_order(argv: list[str], tokens: list[str]) -> bool:
    it = iter(argv)
    return all(any(token == arg or token in arg for arg in it) for token in tokens)


def project(obj: dict, fields: str | None, allowed: set[str]) -> dict:
    if fields is None:
        return obj
    wanted = [f.strip() for f in fields.split(",") if f.strip()]
    for field in wanted:
        if field not in allowed:
            die(f'Unknown JSON field: "{field}"\nAvailable fields:\n  '
                + "\n  ".join(sorted(allowed)))
    return {field: obj.get(field) for field in wanted}


# --- the model ------------------------------------------------------------

def issue_view(state: dict, raw: dict) -> dict:
    repo = state["repo"]
    number = int(raw["number"])
    blockers = state.get("blocked_by", {}).get(str(number), [])
    nodes = [blocker_node(state, b) for b in blockers]
    return {
        "number": number,
        "title": raw.get("title", f"issue {number}"),
        "body": raw.get("body", ""),
        "labels": [{"name": name} for name in raw.get("labels", [])],
        "url": f"https://github.com/{repo}/issues/{number}",
        "state": raw.get("state", "OPEN"),
        "author": {"login": raw.get("author", "maintainer")},
        "assignees": [],
        "createdAt": "2026-09-01T00:00:00Z",
        "updatedAt": "2026-09-01T00:00:00Z",
        "blockedBy": {"nodes": nodes[:BLOCKED_BY_MAX], "totalCount": len(nodes)},
    }


def blocker_state(state: dict, blocker: dict) -> str:
    if blocker.get("state"):
        return blocker["state"]
    if blocker["repo"] == state["repo"]:
        local = state.get("issues", {}).get(str(blocker["number"]))
        if local:
            return local.get("state", "OPEN")
    return "OPEN"


def blocker_node(state: dict, blocker: dict) -> dict:
    """The GraphQL shape gh asks for: id, number, title, url, state, repository."""
    repo, number = blocker["repo"], int(blocker["number"])
    return {
        "id": f"I_fake_{repo.replace('/', '_')}_{number}",
        "number": number,
        "title": blocker.get("title", f"issue {number}"),
        "url": f"https://github.com/{repo}/issues/{number}",
        "state": blocker_state(state, blocker),
        "repository": {"nameWithOwner": repo},
    }


def blocker_rest(state: dict, blocker: dict) -> dict:
    """The REST shape: lower-case state, and the repository only as a URL."""
    repo, number = blocker["repo"], int(blocker["number"])
    return {
        "number": number,
        "title": blocker.get("title", f"issue {number}"),
        "state": blocker_state(state, blocker).lower(),
        "html_url": f"https://github.com/{repo}/issues/{number}",
        "repository_url": f"https://api.github.com/repos/{repo}",
    }


def pull_view(state: dict, raw: dict) -> dict:
    repo = state["repo"]
    number = int(raw["number"])
    status = raw.get("state", "OPEN")
    return {
        "number": number,
        "title": raw.get("title", f"pull {number}"),
        "headRefName": raw["headRefName"],
        "baseRefName": raw.get("baseRefName", "main"),
        "url": f"https://github.com/{repo}/pull/{number}",
        "isDraft": raw.get("isDraft", False),
        "body": raw.get("body", ""),
        "state": status,
        "mergedAt": "2026-09-02T00:00:00Z" if status == "MERGED" else None,
        "closedAt": "2026-09-02T00:00:00Z" if status in ("MERGED", "CLOSED") else None,
        "author": {"login": raw.get("author", "worker")},
    }


# --- commands -------------------------------------------------------------

def cmd_auth(state: dict, args: list[str]) -> None:
    if args[:1] != ["status"]:
        die(f"fake gh: unsupported: auth {' '.join(args)}")
    if not state.get("authenticated", True):
        die("You are not logged into any GitHub hosts. To log in, run: gh auth login")
    sys.stderr.write("github.com\n  Logged in to github.com account maintainer (keyring)\n")


def cmd_repo(state: dict, args: list[str]) -> None:
    if args[:1] != ["view"]:
        die(f"fake gh: unsupported: repo {' '.join(args)}")
    fields = pop_flag(args, "--json")
    owner, name = state["repo"].split("/")
    obj = {
        "nameWithOwner": state["repo"],
        "name": name,
        "owner": {"login": owner},
        "url": f"https://github.com/{state['repo']}",
        "defaultBranchRef": {"name": state.get("default_branch", "main")},
    }
    print(json.dumps(project(obj, fields, REPO_FIELDS)))


def cmd_issue(state: dict, args: list[str]) -> None:
    verb, rest = args[0] if args else "", args[1:]
    fields = pop_flag(rest, "--json")
    issues = state.get("issues", {})

    if fields and "blockedBy" in fields.split(",") and not state.get("blocked_by_field", True):
        # An older gh that predates the field.
        die('Unknown JSON field: "blockedBy"')

    if verb == "list":
        wanted = (pop_flag(rest, "--state", "-s", default="open") or "open").upper()
        limit = int(pop_flag(rest, "--limit", "-L", default="30"))
        found = [
            issue_view(state, raw) for raw in issues.values()
            if wanted == "ALL" or raw.get("state", "OPEN") == wanted
        ]
        # gh lists newest first.
        found.sort(key=lambda i: -i["number"])
        print(json.dumps([project(i, fields, ISSUE_FIELDS) for i in found[:limit]]))
        return

    if verb == "view":
        number = rest[0] if rest else ""
        raw = issues.get(str(number).lstrip("#"))
        if raw is None:
            die(f"GraphQL: Could not resolve to an issue or pull request with the number of {number}. (repository.issue)")
        print(json.dumps(project(issue_view(state, raw), fields, ISSUE_FIELDS)))
        return

    die(f"fake gh: unsupported: issue {' '.join(args)}")


def cmd_pr(state: dict, args: list[str]) -> None:
    verb, rest = args[0] if args else "", args[1:]
    if verb != "list":
        die(f"fake gh: unsupported: pr {' '.join(args)}")
    fields = pop_flag(rest, "--json")
    wanted = (pop_flag(rest, "--state", "-s", default="open") or "open").upper()
    head = pop_flag(rest, "--head", "-H")
    limit = int(pop_flag(rest, "--limit", "-L", default="30"))
    accept = {
        "OPEN": {"OPEN"}, "CLOSED": {"CLOSED", "MERGED"},
        "MERGED": {"MERGED"}, "ALL": {"OPEN", "CLOSED", "MERGED"},
    }[wanted]
    found = [
        pull_view(state, raw) for raw in state.get("pulls", [])
        if raw.get("state", "OPEN") in accept and (head is None or raw["headRefName"] == head)
    ]
    found.sort(key=lambda p: -p["number"])
    print(json.dumps([project(p, fields, PR_FIELDS) for p in found[:limit]]))


def cmd_api(state: dict, args: list[str]) -> None:
    paginate = pop_switch(args, "--paginate")
    slurp = pop_switch(args, "--slurp")
    if slurp and not paginate:
        die("the `--slurp` option is only supported with `--paginate`")
    if not args:
        die("fake gh: unsupported: api with no path")
    owner, name = state["repo"].split("/")
    url = urlsplit(args[0].replace("{owner}", owner).replace("{repo}", name).lstrip("/"))
    parts = url.path.split("/")
    per_page = int(parse_qs(url.query).get("per_page", [PAGE])[0])

    # repos/<owner>/<name>/issues/<n>/dependencies/blocked_by
    if len(parts) == 7 and parts[0] == "repos" and parts[3] == "issues" and parts[5:] == ["dependencies", "blocked_by"]:
        repo, number = f"{parts[1]}/{parts[2]}", parts[4]
        if not state.get("dependencies_api", True) or repo != state["repo"] or number not in state.get("issues", {}):
            not_found()
        items = [blocker_rest(state, b) for b in state.get("blocked_by", {}).get(number, [])]
        pages = [items[i:i + per_page] for i in range(0, len(items), per_page)] or [[]]
        if not paginate:
            print(json.dumps(pages[0]))
        elif slurp:
            print(json.dumps(pages))
        else:
            sys.stdout.write("".join(json.dumps(page) for page in pages) + "\n")
        return

    die(f"fake gh: unsupported: api {args[0]}")


def not_found() -> None:
    body = json.dumps({
        "message": "Not Found",
        "documentation_url": "https://docs.github.com/rest",
        "status": "404",
    })
    die("gh: Not Found (HTTP 404)", stdout=body)


COMMANDS = {"auth": cmd_auth, "repo": cmd_repo, "issue": cmd_issue, "pr": cmd_pr, "api": cmd_api}


def main(argv: list[str]) -> None:
    log(argv)
    state = load()
    args = list(argv)
    target = pop_flag(args, "-R", "--repo")
    if target and target != state["repo"]:
        die(f"GraphQL: Could not resolve to a Repository with the name '{target}'. (repository)")

    for failure in state.get("failures", []):
        if contains_in_order(argv, failure["tokens"]):
            die(failure.get("stderr", "fake gh: scripted failure"), code=failure.get("code", 1))

    if not args or args[0] not in COMMANDS:
        die(f"fake gh: unsupported: {' '.join(argv)}")
    if args[0] != "auth" and not state.get("authenticated", True):
        die("To get started with GitHub CLI, please run:  gh auth login", code=4)
    COMMANDS[args[0]](state, args[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
