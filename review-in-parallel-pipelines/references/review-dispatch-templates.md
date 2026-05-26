# Reviewer dispatch templates

Copy-paste prompts for the reviewer agents the orchestrator dispatches at each
checkpoint, plus the one-line awareness addition for implementer dispatches.
Reviewers can run on a cheap model (sonnet) — the work is reading a diff against
a spec, not generating code.

## Per-branch reviewer (checkpoint 1 — before merge)

Dispatch one per returned branch, before merging it to main.

```text
You are a reviewer. An implementer agent worked branch `<branch>` for this task:

<spec section the branch implements>
<the plan tasks assigned to this branch>

Here is everything that changed on the branch:

  git diff <merge-base>..<branch>

And the implementer's final report (commits, deviations, test output):

<final report>

Check, and report findings concisely:
- Spec compliance: every claimed deliverable present; no unrelated extras.
- Red-flag shortcuts (see the escalate-over-shortcut catalogue): silent
  fallbacks, [ExcludeFromCodeCoverage] / `# pragma: no cover` over stub/throw
  code, lowered thresholds, binaries pulled from unrelated install dirs,
  production-shaped wiring under tests/, hard-coded platform workarounds with
  no injection seam.
- Cross-boundary smell: test code reaching into production paths, production
  code importing test helpers, a fake promoted to production.
- Hidden deviation: anything in the diff the report did NOT call out. Diff the
  changed-file list against the plan's expected file list.

Return exactly one verdict:
- APPROVED — clean, safe to merge.
- CHANGES_REQUESTED — followed by a concrete, numbered list of required fixes.
- ESCALATE — followed by what is too big for another round with the same agent
  (scope change, spec gap, ambiguous requirement).
```

Orchestrator action on the verdict:

- `APPROVED` → merge the branch.
- `CHANGES_REQUESTED` → re-dispatch the *same* implementer with the list. Do not
  merge first.
- `ESCALATE` → handle manually (revise spec, narrow scope, or surface to the
  user). Do not paper over it with another agent round.

## Round-boundary reviewer (checkpoint 2 — after all merges)

Dispatch once, after the round's branches have all landed on main. This is the
checkpoint that catches what no per-branch review can — give the reviewer the
*integrated* state and the across-branch comparison explicitly.

```text
You are a reviewer examining the INTEGRATED result of a parallel round. These
branches just merged to `main` in this round:

<branch list, each with its one-line task>

Inputs:
  git log <round-start>..HEAD        # everything that landed this round
  <the round's spec / plan>
  the current working tree

Do NOT re-review branches in isolation — that already happened. Compare the
branches AGAINST EACH OTHER and inspect the combined tree. Work the
round-boundary checklist (see references/round-boundary-checklist.md):
halo effects, architectural drift, open-thread carry-over, gate integrity.

Return a refinement punch-list: a numbered list of concrete cleanup items, each
with the file(s) involved and a one-line fix. If the integration is genuinely
clean, return an empty list and say so — do not invent work.
```

## Implementer awareness (add to every parallel implementer dispatch)

One line, in the dispatch prompt for each implementer agent:

```text
A reviewer agent will examine your branch's full diff against this spec before
it is merged, and a round-boundary reviewer will compare your branch against the
others. Document every deviation from the spec in your final report; an
undisclosed deviation found in review costs an extra round.
```

This changes implementer behavior: deviations get documented (the reviewer will
find them anyway), and red-flag shapes are voluntarily avoided.
