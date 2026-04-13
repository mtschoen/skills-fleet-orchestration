---
name: fleet-orchestration
description: "Use when dispatching subagents across multiple LOCAL PROJECT REPOSITORIES — feature implementation, maintenance sweeps, or fleet-wide investigation across the user's project directory. Triggers: 'spawn agents to fix X across all my projects', 'run a maintenance pass', 'work on tasks from several repos at once', use of projdash MCP tools (list_projects, find_dirty, find_stale_maintenance) to plan multi-repo work. Extends superpowers:dispatching-parallel-agents with cross-repo governance."
---

# Fleet Orchestration

## Relationship to `superpowers:dispatching-parallel-agents`

**Builds on** `superpowers:dispatching-parallel-agents`. That skill covers the universal mechanics: when to dispatch (independent domains), agent prompt structure, common mistakes, verification. **Read it first; this skill assumes you know it.**

This skill adds the layer that's specific to working **across multiple repositories owned by the same user** — where the parent skill's "one codebase" assumption breaks down and new failure modes appear:

| Concern | Parent skill | This skill |
|---|---|---|
| When to parallelize | ✅ | inherits |
| Agent prompt structure | ✅ | inherits, adds repo-specific must-includes |
| One codebase, multiple bugs | ✅ | — |
| Multiple repos, one task each | — | ✅ |
| Pre-dispatch task selection / triage | — | ✅ |
| User pre-approval shortlist | — | ✅ |
| Result triage (orchestrator answers questions) | — | ✅ |
| Maintenance vs feature dual mode | — | ✅ |
| Maintenance breadcrumbs (`.maintenance.json`) | — | ✅ |
| Cross-repo permission inheritance | — | ✅ |
| Worktree isolation is intra-repo only | — | ✅ |

If you're fixing 3 unrelated test failures in **one** project, use the parent skill alone. If you're picking tasks from PLAN.md files across **N** projects, use both.

## Overview

You are the orchestrator. The parent skill tells you how to brief and dispatch agents. This skill tells you how to **select** which work goes to which agent across the fleet, **gate** the user before dispatching, and **triage** results before they reach the user.

The single biggest fleet-orchestration failure mode is dispatching a vague task and then forwarding the agent's open questions to the user verbatim. **You** are responsible for answering open questions — by reading more code, by checking git history, by understanding the data model — before bothering the user. The parent skill's "review and integrate" step is necessary but not sufficient: across repos, you also need to *answer*, not just *summarize*.

## Two modes: never mix them

**Maintenance pass**: bounded, mechanical, no product judgment.
- Push latest branch tip if behind
- Lint changed files
- Prune merged worktrees, `[gone]` branches
- Tick PLAN.md tasks completed by recent commits
- Run tests on current HEAD

**Feature pass**: PLAN-driven, may require interpretation.
- Implement an unchecked PLAN.md item
- Fix a reported bug
- Refactor a module

A feature pass needs the triage gate and user pre-approval below. A maintenance pass needs neither — definitionally bounded tasks just run, breadcrumbs prevent re-runs. **A maintenance task that suddenly needs a product call is a leaky abstraction**: stop, demote it to a feature task, and run it through the feature gate.

## Pre-dispatch triage (feature mode)

For each candidate task, before spawning anything, answer four questions:

1. **Is the scope crisp?** Does the PLAN bullet name a specific file/feature, or is it an aspiration ("improve UX")?
2. **Are there hidden coupling questions?** Spend 2–3 minutes reading the surrounding code. If a single field/function turns out to be load-bearing across many files, the task is not bounded. (Real example: a "filename" column that turns out to be a lookup key in five other modules — looks like a label, isn't.)
3. **Would a human need to make a product call mid-implementation?** "Should rename touch disk?" "Which interpretation of this note?" If yes, no agent should be touching it.
4. **Is the test surface trustworthy?** Tests-pass ≠ correct-behavior when the task is about semantics rather than mechanics.

### Decision

- **Green** (all four pass) → eligible for dispatch.
- **Yellow** (one concern) → eligible, but the agent's brief must include "stop and report if you hit X."
- **Red** (two+ concerns, or product call required) → **drop from the dispatch list**. Produce a handoff prompt for the user (see below).

Triage runs **before** the user pre-approval step — the user shouldn't have to evaluate red tasks at all.

### Red flag handoff format

When refusing to dispatch, give the user a paste-ready way to start a new session:

```
This task needs supervised work in a fresh session. Try:

  cd <absolute path to repo>
  claude

Then paste:

> Working in <project>. Task: <PLAN line, verbatim>.
> Before implementing, investigate: <specific files / functions / db columns>.
> The ambiguity is: <concrete question>.
> Ask the user before writing code.
```

This gets the work done with proper context, without burning your orchestrator turn on something it can't safely do.

## User pre-approval (feature pass only)

After triage, **before dispatching**, present the shortlist to the user and wait for approval. Triage filters tasks the orchestrator *knows* are bad; user approval catches tasks the orchestrator *doesn't know* are bad — usually because the user has context (recent decisions, in-flight refactors, "that area is weedy") that isn't in the codebase or git history.

Format the shortlist as a compact table:

```
About to dispatch N agents in parallel. Approve?

  # | Project    | Task                                | Risk
  --|------------|-------------------------------------|------
  1 | projdash   | Search/filter (PLAN.md:55)          | green
  2 | llamalab   | Edit model filename (PLAN.md:676)   | yellow
  3 | cstb       | Graceful shutdown (PLAN.md:48)      | green

Yellow notes:
  2: "filename" looks like a label, haven't verified it isn't
     load-bearing. Agent will stop and report if it hits coupling.

Reply: "go", "skip N", "all but N", or ask about any task.
```

Required elements:
- **PLAN.md line numbers** so the user can jump to source.
- **Risk color** (green/yellow — reds are already filtered out) so attention goes to the right rows.
- **One-line "what worried me"** for every yellow.
- **Shorthand response format** so approval is a 2-second decision.

The act of writing the yellow note is itself a forcing function — if you can't articulate what worried you, you probably haven't read enough code to dispatch responsibly. Go read more.

### When to skip the prompt

- **Maintenance pass**: just go.
- **User explicitly said "just go"** in this session or in CLAUDE.md.

Feature passes always prompt, even when everything looks green.

## Briefing additions for fleet work

The parent skill's prompt structure applies. On top of it, every fleet brief must include:

- **Sync before starting**: agent must run `git pull --ff-only` and `git push` (if upstream exists and local is ahead) **before touching code**. Stops divergence between fleet sweeps and prevents work on a stale tree. If pull is non-fast-forward or push is rejected, STOP and report — do not force, rebase, or merge without orchestrator instruction.
- **Absolute repo path** (`C:\Users\mtsch\<project>`) — agents inherit cwd from the orchestrator, not from the task.
- **One-sentence project description**, or "read CLAUDE.md in this directory before starting."
- **Verbatim PLAN.md line + line number** they're implementing.
- **Specific file paths you've already identified** as relevant (the triage reading was not wasted — pass it to the agent).
- **Pre-answered ambiguity** — if triage flagged a yellow concern, the brief must say what to do if the agent hits it. Don't make the agent re-derive your judgment.
- **Permission boundary**: "if Edit/Write is denied for files under <repo path>, STOP immediately and report it as a permission issue. Do not work around."
- **Hard prohibitions**: "Do NOT commit. Do NOT push. Leave changes in the working tree."
- **Concise reporting format**: files changed (with one-line summary each), test results, anything needing human review.

A great fleet brief includes the answer to the ambiguity you'd otherwise have had to chase down later.

## Cross-repo dispatch mechanics

The parent skill covers parallel dispatch. Two cross-repo specifics:

- **One repo per agent.** Two agents in the same repo collide unless you use `isolation: "worktree"`. Across different repos, isolation is automatic — they're separate filesystems.
- **`isolation: "worktree"` is intra-repo only.** It cannot put agent A in repo X and agent B in repo Y. If you need both, dispatch them to separate repos directly; the filesystem provides the isolation.
- **Verify worktree isolation actually took.** If you requested `isolation: "worktree"` and the agent's result doesn't include a `worktreePath`, isolation silently failed and the agent worked on the parent tree. Assume cross-contamination and investigate before dispatching more parallel work.

## Result triage (the part the parent skill doesn't cover)

The parent skill's "review and integrate" step assumes you can read the diffs and decide. Across repos with rich domain context, that's not enough — agents will frequently return "needs human review" items that are actually answerable from the code, and forwarding them wastes the user's attention.

When agents return, **do not** forward open questions to the user. Instead:

1. For each "needs human review" item, decide if you can answer it yourself by reading code.
2. Read the relevant files. Check git history. Look at adjacent features. Trace data flow.
3. Form a recommendation backed by evidence (concrete `file:line` references).
4. Either apply the answer yourself, or surface it to the user **with your recommendation and the evidence**, not as a raw open question.

Only bubble up to the user when:
- The question is genuinely a product call (only they know which interpretation they meant), or
- Two interpretations are equally plausible after investigation, or
- The fix requires a destructive action you need authorization for.

Format for bubbling up:
> The agent asked X. I read `file.py:142` and `other.py:88` — Y is true, so option (b) is the right read. **Recommend**: revert and reissue with scope (b). Confirm?

This is the most important difference between this skill and the parent. The parent assumes a debugging context where the right answer is in the test output. Across repos with PLAN-driven work, the right answer is usually in code the agent didn't read because you didn't tell it to.

## Maintenance breadcrumbs

Maintenance state lives in each repo as `.maintenance.json` (gitignored). projdash exposes two MCP tools:

- `mcp__projdash__get_maintenance_state(name)` — read one project's breadcrumbs
- `mcp__projdash__find_stale_maintenance(task_name?)` — find projects where a task is stale

Quick format reference (full schema in `references/maintenance-format.md`):

```json
{
  "version": 1,
  "tasks": {
    "push-latest": {
      "kind": "per-commit",
      "last_run_commit": "<full-sha>",
      "last_run": "2026-04-06T14:23:11Z",
      "status": "clean"
    },
    "stale-worktrees": {
      "kind": "time-based",
      "last_run": "2026-04-06T14:23:11Z",
      "interval_days": 30,
      "status": "clean"
    }
  }
}
```

**Staleness rules** (already enforced by projdash):
- `per-commit` → stale when `last_run_commit != git rev-parse HEAD`
- `time-based` → stale when `now - last_run > interval_days`
- A task with `status: "failed"` at the **same** HEAD is **not** stale — re-running a failed task at an unchanged commit will fail again. Wait for HEAD to move.

**Runner contract:**
1. Read current state with `get_maintenance_state` or directly from disk.
2. Skip if `is_task_stale` returns False.
3. Do the work.
4. Write a new entry with `status` and either `last_run_commit` (per-commit) or `last_run` (time-based). Use `projdash.scanner.maintenance.write_maintenance_state` so `.gitignore` gets updated automatically.
5. Never delete entries — overwrite in place.

## Workflows

### Maintenance pass

```
1. find_stale_maintenance(task_name="push-latest")
   → ["llamalab", "site"]                  # other repos clean, skipped
2. For each stale project:
   - cd into repo
   - run the operation
   - update .maintenance.json on success or failure
3. Report: "pushed 1/2, site failed (no upstream)"
```

Re-running 5 minutes later returns only `["site"]`. Cheap.

### Feature pass

```
1. Identify candidate tasks (read PLAN.md from N projects).
2. Triage each (the four questions above). Drop reds, produce handoff prompts.
3. Present green/yellow shortlist to the user. Wait for approval.
4. For approved tasks: write rich briefs with pre-answered ambiguities.
5. Dispatch all approved agents in ONE message (per parent skill).
   One agent per repo.
6. When they return, triage results yourself before reporting.
7. For each "needs review" item: investigate, recommend, then ask.
8. Present final summary as a per-project status table.
```

## Cross-repo permission notes

- Subagents inherit this session's directory permissions, not the orchestrator's cwd.
- If a sibling repo isn't in the allowed list, the agent will hit Edit/Write denials. Tell the agent in the brief to STOP on denial, not work around.
- The user can preemptively grant access with `/add-dir <path>` or by listing repos in `~/.claude/settings.json` under `permissions.additionalDirectories`.
- **Bash commands run with full user privileges regardless of `--add-dir`** — the directory sandbox only affects file tools, not shell.
- Empirically, sibling-repo file access often *just works* without `/add-dir` if the user's settings allow a parent directory. Don't assume — but don't over-engineer either. If denials happen, surface them; if they don't, proceed.

## Anti-patterns specific to fleet work

(Inherits all anti-patterns from the parent skill. These are additions.)

- Dispatching a feature pass without showing the user the shortlist first.
- Spawning a subagent for a task you haven't read the surrounding code for.
- Forwarding agent open questions to the user verbatim instead of investigating them yourself.
- Mixing maintenance and feature tasks in one pass.
- Using `isolation: "worktree"` for cross-repo parallelism (it doesn't work that way — different repos are already isolated).
- Letting an agent commit/push without orchestrator review.
- Trusting "all tests pass" as proof of correctness for semantic changes.
- Re-running maintenance tasks on projects that haven't changed since their last clean run.
- Writing a yellow risk note without being able to articulate exactly what worried you.
