# Review in Parallel Pipelines — Skill Handoff

**Status:** Not yet built. This document briefs the agent who will create the skill. It may end up as a revision to `superpowers:subagent-driven-development` rather than a standalone skill — skill author decides after reading.

## Core thesis

Parallelism does not replace review. Running N agents concurrently against isolated worktrees is an execution pattern; review gates sit orthogonally to it. When the orchestrator skips review because "there are N branches flying and I'm busy watching," silent-weird solutions land in the merged product — the precise failure mode that review exists to catch.

This skill formalizes review as a first-class phase of parallel execution, describes per-branch and round-boundary review patterns, and positions cleanup rounds as scheduled work rather than afterthoughts.

## When to apply

Any execution pattern with ≥2 concurrent implementer agents dispatching into isolated branches / worktrees, specifically:
- `superpowers:subagent-driven-development` run in parallel mode
- `superpowers:dispatching-parallel-agents` for broader fan-out
- Fleet orchestration across repos when per-repo work has similar review needs

If only one agent is running at a time, `subagent-driven-development`'s existing two-stage review is sufficient and this skill doesn't add value.

## The three review checkpoints

### 1. Per-branch review — before merge

After an implementer agent returns with commits on its worktree branch, and BEFORE the orchestrator merges to main:

Dispatch a reviewer agent (sonnet model is fine — cheap) with:
- The diff (`git diff <merge-base>..<branch>`)
- The spec section the branch implements
- The plan tasks that were assigned
- The branch's final report (commits, deviations, test output)

Ask the reviewer to check for:

- **Spec compliance**: every claimed deliverable is present. No unrelated extras.
- **Red-flag shortcuts** (from the `escalate-over-improvise` skill's pattern list): binaries copied from unrelated apps, `[ExcludeFromCodeCoverage]` hiding unimplemented production paths, production-shaped code in test projects, hard-coded OS/emulator workarounds without injection seams, silent fallbacks, threshold lowering to escape a gate.
- **Cross-boundary smell**: test code reaching into production paths, production code importing test helpers, fakes promoted to production without review.
- **Dead or duplicated content**: functions shadowed by a parallel branch's version, types defined twice, tests duplicating coverage.
- **Hidden deviation**: deviations the final report didn't call out — run a diff check against the plan's expected file list.

Reviewer's output is a structured verdict:
- `APPROVED` → orchestrator merges
- `CHANGES_REQUESTED` with a concrete list → orchestrator re-dispatches implementer with the list
- `ESCALATE` → reviewer surfaces something too big for another round with the same agent; orchestrator handles manually (e.g., scope change, spec revision)

### 2. Round-boundary review — after all merges in a round

After a parallel round's branches all land on main:

Dispatch a reviewer agent against the integrated state:
- Git log since the round began
- All modified/added files
- The spec and plan

Check for:

- **Halo effects**: branch A pulled files forward that branch B also created; main now has one of each but also might have dead stubs. Branch X added a NuGet package that overlaps with branch Y's. Two branches each added Kover exclusions for similar patterns — could they consolidate?
- **Architectural drift**: the round's work stayed within the planned shape, or did it bulge into unplanned areas?
- **Open thread carry-over**: deviations across branches that logically aggregate (multiple branches noted "we'll clean this up later") — surface them as a cleanup round rather than letting them accumulate.
- **Gate integrity**: coverage, build, tests all still green? Any silently-skipped test that used to run?

Output is a refinement punch-list.

### 3. Refinement round as a scheduled phase

Treat the punch-list from (2) as the next round's work. The orchestrator dispatches cleanup agents against it before moving to the NEXT planned phase. Refinement is a first-class phase, not an afterthought.

Refinement rounds are usually SMALL — often 1–3 tasks — and often serial (cleanup tasks tend to depend on each other). They should NOT compete with new-feature phases for attention.

## Implementer-agent awareness

Implementer agents should be TOLD, in their dispatch prompt, that a reviewer will examine their branch before merge. This changes behavior:
- Agents take the "would a senior engineer approve this" question more seriously when they know a reviewer is definitely going to ask
- Deviations get documented more thoroughly (because the reviewer will find them anyway)
- Red-flag patterns are voluntarily avoided because the agent knows they'll be called out

Make the reviewer's existence explicit in the implementer dispatch template.

## Cost

Adds ~N reviewer runs per parallel round (one per branch) plus ~1 post-merge reviewer run. Sonnet model keeps the cost-per-run modest.

Break-even analysis: one caught OBS-DLL-copy class of issue avoided per round pays for the full review layer. Empirically (from the WindowStream session), each round of 3–14 agents produced at least one such issue. Review has strongly positive ROI for parallel execution.

## Integration with existing skills

- **`superpowers:subagent-driven-development`** — this skill may be folded in as an extension of that skill's "When multiple agents run in parallel" section. Alternatively, keep as companion; the existing skill covers the per-task pattern, this covers the multi-agent-per-phase pattern.
- **`escalate-over-improvise`** (new, see sibling handoff) — the implementer-side discipline that reviewers enforce. The two skills reference each other.
- **`pushback`** — Claude→user pushback. This skill is orchestrator→agent review, which is different but resonant.

## Suggested structure

```
~/skills-dev/review-in-parallel-pipelines/
  SKILL.md                       # thesis, when to apply, three-checkpoint model
  references/
    per-branch-review.md         # dispatch template + check list
    round-boundary-review.md     # halo / drift / gate integrity check list
    refinement-rounds.md         # cleanup as first-class phase
    implementer-awareness.md     # prompt additions for implementers
    cost-vs-value.md             # ROI discussion, when to skip
```

Or, if merged into `subagent-driven-development`, add a major subsection titled something like "Parallel execution" that subsumes this content.

## Session-specific context (for the skill author)

The WindowStream session (April 2026) ran rounds of 2, 3, 6, 14 parallel agents with `isolation: "worktree"` and `run_in_background: true`. The orchestrator merged branches via `git merge --no-ff` after verifying build/test green, but did NOT dispatch reviewers. Silent-weird issues that reached main (caught only after the fact by a human):

- OBS DLL dependency (Phase 12)
- `CliServices.CreateDefault()` throw-stub with coverage exclusion (Phase 11)
- Adapters in test project (Phase 12)
- Hard-coded emulator codec name in production `MediaCodecDecoder` — later confirmed safe (default + injection seam), but the orchestrator didn't verify before merging
- NAL 3-byte start codes missing — didn't surface until an emulator test actually ran (Phase 13)
- `[ExcludeFromCodeCoverage]` sprinkled throughout FFmpeg encoder for "native-only paths" — partially legitimate, partially hiding untested logic; would have benefited from review

These would all have been findable by a reviewer agent looking at `git diff main..branch` with a short check list.

## Deployment

Per user's standard skill workflow (`~/skills-dev/` → `~/.claude/skills/` → GitHub if published).
