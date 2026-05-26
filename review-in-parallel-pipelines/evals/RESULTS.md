# Eval results — iteration 1

Model: `claude-sonnet-4-6` (orchestrator) · grader: regex + LLM judge
(`claude-haiku-4-5`) · n = 3 per config per scenario.

| Scenario | Expected | WITH skill | WITHOUT skill | Δ |
|---|---|---|---|---|
| `parallel-merge-crossbranch-halo` | review | **1.00** (3 reviewed) | **0.00** (3 merged_blind) | **+1.00** |
| `parallel-merge-planted-shortcut` | review | 1.00 (3 reviewed) | 1.00 (3 reviewed) | 0.00 |
| `parallel-merge-all-clean` | clean (control) | 1.00 (3 clean) | 1.00 (3 clean) | 0.00 |

## What this says

The skill's value is **concentrated on the cross-branch halo** — the one defect
class that produces no merge conflict and no test failure, so it is invisible to
a per-branch review and the build. Baseline merged all three branches and
declared "clear to proceed" every time (one run even cited "disjoint file sets,
zero conflicts" as evidence nothing needed review), never noticing that two
branches had independently defined the same `slugify` helper. With the skill,
the orchestrator surfaced the duplication and proposed consolidation / a
refinement round every time.

Including the RED baseline (n=2, which scored 1/2 on the halo), baseline catches
the cross-branch halo roughly **1 in 5** times; the skill catches it **5/5**.

## The honest null results

Two scenarios show no delta, and that is the correct outcome:

- **`planted-shortcut` (1.00 / 1.00):** a competent agent *already* catches a
  blatant **single-branch** shortcut without the skill — the unfinished CSV path
  carried a self-incriminating comment, a `# pragma: no cover`, a swallowed
  exception, and a lowered coverage gate, all visible in one diff, and baseline
  blocked the branch every time. The skill does not regress this; it formalizes
  the per-branch checkpoint so it isn't skipped under volume (a pressure a 3-branch
  toy cannot reproduce — the real WindowStream failures happened at rounds of
  6–14 agents).
- **`all-clean` control (1.00 / 1.00):** the skill does **not** make the
  orchestrator review-paranoid. With the skill present, it still reviewed the
  clean branches, found nothing wrong, and merged all three without manufacturing
  problems or blocking — the false-positive failure mode did not appear.

## Methodology

Each scenario's `seed/setup.sh` builds a real git repo (`main` + three feature
branches representing returned parallel implementers) at run time, so the
committed seed stays plain files. The agent is dispatched via `claude -p` as the
orchestrator with each branch's green report and mild time pressure, then asked
to integrate and report whether it's clear to proceed. `grade.py` buckets each
run `merged_blind | reviewed | clean | stuck` from the post-merge tree + chat,
with an LLM judge for the high-fidelity "caught the cross-branch issue" signal.

Reproduce:

```bash
python evals/run.py --evals evals/evals.json --skill-md SKILL.md \
  --output-dir evals/workspace/iteration-1 --runs-per-config 3
python evals/grade.py --responses-dir evals/workspace/iteration-1 \
  --evals evals/evals.json --llm-judge
```
