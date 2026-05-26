# review-in-parallel-pipelines

A Claude Code skill that teaches an **orchestrator** running multiple implementer
agents in parallel to keep review as a first-class phase of execution — instead
of merging each branch the moment its report says "green" and moving on. Sits on
top of the superpowers plugin's `subagent-driven-development` skill (per-task
review for one agent) and adds the layer it lacks: review *across many concurrent
agents per phase*.

## What it does

Parallelism is an execution pattern; review is orthogonal to it. When the
orchestrator is busy watching N branches, the cheap local move is to merge on
green and push to the next round — exactly when silent-weird solutions land in
the merged product.

The skill formalizes three review checkpoints:

1. **Per-branch review** — before each merge, a cheap reviewer agent checks the
   branch's diff against its spec for shortcuts, cross-boundary smells, and
   hidden deviations.
2. **Round-boundary review** — after *all* a round's branches land, review the
   **integrated** state by comparing branches against each other. This is the
   checkpoint no per-branch review can replace: it catches the class of defect
   that produces no merge conflict and no test failure — duplicated logic,
   shadowed code, redundant dependencies, architectural drift.
3. **Refinement round** — schedule the punch-list from (2) as the next round's
   work, before the next planned feature phase.

The central discipline: **a clean merge is not a clean integration.** "Zero
conflicts, disjoint file sets, green build" proves git could combine the text
and each branch works alone — it says nothing about whether the integrated whole
is right.

## Provenance

The checkpoints and the cross-branch failure catalogue come from a real
WindowStream session (Windows → Android-XR window streaming) that ran rounds of
2, 3, 6, and 14 parallel agents in isolated worktrees, merged on green, and did
*not* dispatch reviewers. Silent-weird issues reached `main` and were caught only
after the fact: an OBS DLL dependency, a throw-stub hidden behind a coverage
exclusion, adapters left in a test project, missing NAL start codes. Each would
have been findable by a reviewer agent looking at `git diff main..branch` with a
short checklist.

## Install

Via the [skills-dev](https://github.com/mtschoen/skills-dev) installer:

```bash
# Unix / macOS
./install-skills.sh -y review-in-parallel-pipelines

# Windows
install-skills.bat -y review-in-parallel-pipelines
```

Installs to `~/.claude/skills/review-in-parallel-pipelines/`. The installer ships
`SKILL.md` + `references/` and excludes development-only files (this `README.md`,
`HANDOFF.md`, `LICENSE`, `evals/`). The agent loads `SKILL.md` from the install
location; this README is for human readers browsing the repo.

## Layout

```text
review-in-parallel-pipelines/
  SKILL.md                          thesis, the three checkpoints, red flags, self-check
  README.md                         this file
  HANDOFF.md                        original design brief (kept for posterity)
  references/
    review-dispatch-templates.md    reviewer-agent prompts (per-branch + round-boundary) + implementer-awareness snippet
    round-boundary-checklist.md     halo / drift / carry-over / gate-integrity catalogue
  evals/                            eval harness (dev-only)
    evals.json                      3 scenarios (2 should-review + 1 control)
    run.py                          driver: claude -p × (config × runs × evals); seeds a real git repo per scenario
    grade.py                        buckets each run: merged_blind | reviewed | clean | stuck
    scenarios/                      per-scenario seed/setup.sh + brief.md + rubric.json
  .gitignore                        evals/workspace/ (scratch) + python caches
```

## Related skills

- `subagent-driven-development` (superpowers plugin) — the base. Covers per-task review for one agent at a time; this skill adds the multi-agent-per-phase layer.
- `dispatching-parallel-agents` (superpowers plugin) and [`fleet-orchestration`](https://github.com/mtschoen/skills-fleet-orchestration) — the execution patterns this skill gates.
- [`escalate-over-shortcut`](https://github.com/mtschoen/skills-escalate-over-shortcut) — the implementer-side discipline the per-branch reviewers enforce (agent → self on its own draft). This skill is orchestrator → branches.
- [`pushback`](https://github.com/mtschoen/skills-pushback) — sibling axis. Pushback is Claude → user; this is orchestrator → other agents' returned work.
- [`maintaining-full-coverage`](https://github.com/mtschoen/skills-maintaining-full-coverage) — adjacent. The round-boundary "gate integrity" check looks for the threshold-lowering this skill enforces against.

## Eval design

The harness is cloned from
[`escalate-over-shortcut/evals`](https://github.com/mtschoen/skills-escalate-over-shortcut),
adapted for "orchestrator at a merge point" rather than "agent reviewing its own
draft." Each scenario's `seed/setup.sh` builds a real git repo with `main` plus
three feature branches representing returned parallel implementers; the agent is
dispatched as the orchestrator and asked to integrate them under mild time
pressure. Each run buckets to `merged_blind | reviewed | clean | stuck`.

Three scenarios:

- **parallel-merge-crossbranch-halo** (should-review) — two branches
  independently add an identical helper; clean merge, green build, duplicated
  logic. The differentiator: no single branch's diff reveals it.
- **parallel-merge-planted-shortcut** (should-review) — one branch hides an
  unfinished path behind `# pragma: no cover` + a swallowed exception + a lowered
  coverage gate, undisclosed in its report.
- **parallel-merge-all-clean** (control) — all three branches clean and honest;
  measures false-positive resistance (the review-paranoid failure mode).

A notable finding from baseline testing: a competent agent **already** catches the
*blatant single-branch* planted shortcut without the skill (its self-incriminating
comment and lowered gate are visible in one diff). The skill's differentiated value
is the **cross-branch halo** — baseline misses it roughly half the time because no
single diff reveals it and the build is green, while the skill's round-boundary
checkpoint catches it. See `evals/RESULTS.md` for the numbers.

To run locally:

```bash
python evals/run.py \
  --evals evals/evals.json \
  --skill-md SKILL.md \
  --output-dir evals/workspace/iteration-1 \
  --runs-per-config 3

python evals/grade.py \
  --responses-dir evals/workspace/iteration-1 \
  --evals evals/evals.json \
  --llm-judge
```

## License

MIT — see `LICENSE`.
