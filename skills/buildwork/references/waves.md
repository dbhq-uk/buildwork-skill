# Waves, hotspots, and why fan-out is usually wrong

## Start here: it is usually wrong

The default failure of every tool in this category is fanning out work that one
agent should simply have done.

A single agent matches or beats a multi-agent system on most benchmarked tasks
given the same tools and the same context. A multi-agent run burns roughly
fifteen times the tokens of a single conversation. Teams have spent months
building elaborate orchestration and found that better prompting of one agent
got them the same result.

Fan-out earns its cost in exactly one situation: **several pieces of work that
genuinely do not touch each other**, where the wall-clock saving is worth the
token multiple and the integration cost.

That is why `plan` can return a refusal, and why the refusal is a result rather
than an error. When it fires, say it plainly and do the work in the session you
are already in.

The refusals, and what each one means:

| Refusal | What it is telling you |
|---|---|
| One issue | There is nothing to parallelise. A worktree and a fresh context cost more than just doing it |
| All issues declare the same files | One piece of work wearing several issue numbers. Ordering cannot save it |
| Cycle in the dependency graph | Nothing can be ordered. Guessing would dispatch work into a dependency it was told to wait for |

## What worktrees do and do not fix

A worktree gives each agent its own HEAD, index and working directory. No
locks, no semaphores, no live file corruption. That converts silent runtime
corruption into visible merge-time conflicts, which is the prerequisite for
every other coordination strategy.

It fixes exactly one class of problem. Three remain:

**1. Shared hotspot files.** Route registries, response headers, a CSP, a
content plan, a lockfile. Every branch touches them and every branch conflicts
on them. Isolation does nothing; it just defers the pile-up to merge time.
This is what `hotspots` in the config exists for, and it is the class buildwork
actually solves.

**2. Semantic conflict.** Agent A writes a helper assuming a signature, agent B
changes that signature on its own branch. Neither branch is broken alone. The
merge is. **buildwork does not solve this** and does not claim to. It is caught
by the domain gate at collection, or by a human reading the diff, or not at
all.

**3. Real-time dependencies.** Agent A builds the API, agent B builds the
client that calls it. That needs sequencing, not isolation, which is what
`blocked_by` edges are for.

## How a wave is packed

1. Hold back anything that cannot start this session: an issue whose blocker
   is open and outside this set, since nothing here will close it, and an
   issue whose blocker is itself held. A blocker in another repository is
   always outside the set, and is never read as a local issue with the same
   number. Each one gets a `!` warning naming the blocker. A closed blocker
   holds nothing.
2. Take everything with no unmet blocker inside this set.
3. Walk them in roadmap order, adding each to the wave unless it claims a file
   already claimed in that wave.
4. Stop at the cap.

## Where the dependency links come from

`plan` reads them in one call: `gh issue list` with the `blockedBy` field,
which lists each blocker with its state and repository. gh asks for the
first 50; an issue with more is read again from the REST dependencies
endpoint, page by page. A gh too old to have the field falls back to that
endpoint for every issue. Either way the plan says which source answered,
in a `~` line.

Only when GitHub gives no answer at all does `plan` read `Blocked by #N` and
`Depends on #N` lines out of the issue body, and it says so, with gh's own
error. A bare `after #N` is not read: "found after #12 shipped" is a
sentence, not a dependency.

**A claim is any declared file, plus any hotspot those files hit.** Two
branches editing one file conflict whether or not somebody listed it as a
hotspot. The hotspot list exists for the files that conflict *even when no
issue admits to touching them* - which is most of them, because issues are
written about outcomes and not about route registries.

## Hotspots

`buildwork.py init` suggests them from the files most often touched across
recent merges. That is a decent proxy and it is only a proxy: it finds the
files that change a lot, which correlates with, but is not the same as, the
files two parallel branches will fight over. Read the suggestions.

A hotspot that no longer exists blocks waves for no reason. `doctor` reports
those.

## Scope, and issues that declare nothing

An issue declares its scope by naming paths in backticks. Everything downstream
depends on that: hotspot detection, wave packing, and the QC scope gate.

An issue that names no files is treated as **unknown scope**, not empty scope:

- It never shares a wave with another unknown-scope issue, because nothing is
  known about whether they collide.
- It is not failed by the QC scope gate, because there is nothing to check
  against. Failing it would train people to declare a directory and move on,
  which is worse than an honest unknown.
- It is reported as a warning in the plan, so it can be fixed at the source.

Better issues make all of this work better. That is deskwork's job, not this
one's.

## The numbers to keep in mind

- **4** concurrent workers is where pull-request-per-agent stops being
  comfortable, and where Paseo tabs stop being readable.
- **2** is the cap on host subagents, which die with your session and send every
  permission prompt to it.
- **15x** the tokens of a single conversation, roughly, for a multi-agent run.
- **1** rework per failed collection. Then a human.
