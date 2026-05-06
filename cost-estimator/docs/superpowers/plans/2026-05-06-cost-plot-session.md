# Cost Plot-Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `plot-session.py` script to the cost-estimator skill that renders one Claude Code session's cost trajectory as an interactive HTML chart (per-turn bars + cumulative line + hover tooltips), so the user can investigate spike sessions surfaced by `summarize.py`.

**Architecture:** Extract the canonical pricing formula from `analyze-month.py` into a new shared `pricing.py` module to remove drift risk. Build `plot-session.py` on top of it: argparse → resolve session ID/path → walk the parent JSONL via a new `iter_assistant_turns()` helper → emit an HTML page with Chart.js (CDN by default, embeddable via `--inline-js`). Subagent costs are summarized in the page caption but not plotted on the timeline — overlay sub-trajectories are deferred to a future Phase 2.

**Tech Stack:** Python 3 (stdlib + optional `orjson`, no new Python deps); Chart.js v4 from `cdn.jsdelivr.net` (or cached locally for `--inline-js`).

---

## Phase 3: Documentation & end-to-end validation

### Task 8: Update `SKILL.md` to mention `plot-session.py`

**Files:**
- Modify: `SKILL.md` (3 small additions)

- [x] **Step 1: Add a new step under "Steps" pointing at plot-session for top sessions**

Find the existing numbered "Steps" list (currently steps 1–5, ending at "Offer to save"). Insert a new step between current step 4 ("Synthesize a markdown report") and current step 5 ("Offer to save"):

```markdown
5. **Plot top spike sessions on demand.** When the report flags a
   top-N session that the user wants to investigate, render its
   per-turn trajectory:
   ```bash
   python <skill-root>/scripts/plot-session.py <session-id-prefix> --open
   ```
   This produces an HTML chart (per-turn bars + cumulative line +
   hover tooltips) at `<skill-root>/reports/session-<prefix>.html`,
   helping the user see *where* in the session the spike happened.
   Pass `--inline-js` for an offline-viewable file. Currently parent-
   only — subagent cost is summarized in the page caption but not
   plotted.
```

Renumber the existing step 5 ("Offer to save") to step 6.

- [x] **Step 2: Add a Phase-2 caveat to "What this skill does not do (yet)"**

Find the existing "What this skill does not do (yet)" section. Add this bullet (placement: above or below the existing "Per-project breakdown" bullet, whichever reads better):

```markdown
- Subagent timeline overlays. `plot-session.py` plots the parent
  JSONL only; subagent costs are summarized in the chart caption but
  not plotted as their own anchored sub-trajectories. Adding overlay
  curves anchored to spawn/finish timestamps is a planned Phase 2.
```

- [x] **Step 3: Update the "Files in this skill" list**

Find the bullet list at the end of `SKILL.md`. Add two bullets and revise the existing analyze-month bullet to mention pricing:

```markdown
- `scripts/pricing.py` — canonical pricing helpers (rates, multipliers,
  `cost_for_turn`, `iter_assistant_turns`). Both retrospective and
  per-session scripts import from here.
- `scripts/analyze-month.py` — JSONL walker and per-turn pricer
  (uses `pricing.py`). Default `--out` is `<skill-root>/reports/`.
- `scripts/summarize.py` — CSV reader and waste-pattern report.
  Default `--csv` is `<skill-root>/reports/sessions.csv`.
- `scripts/plot-session.py` — per-session HTML cost trajectory chart
  (uses `pricing.py`).
```

(Replace the existing analyze-month and summarize bullets with the four-bullet version above.)

- [x] **Step 4: Commit**

```
git add SKILL.md
git commit -m "skill: document plot-session.py and pricing.py"
```

---

### Task 9: Update `README.md`

**Files:**
- Modify: `README.md`

- [x] **Step 1: Read the current README**

```
cat README.md
```

Identify where the existing scripts (analyze-month, summarize) are introduced. The README is a short overview file; the new mention should be one to two sentences.

- [x] **Step 2: Add a brief mention of plot-session**

Add a paragraph or list entry near the existing tooling description:

```markdown
- **`scripts/plot-session.py`** — render a single session's per-turn
  cost trajectory as an interactive HTML chart (Chart.js). Useful for
  investigating a session that `summarize.py` flagged as a top
  spender; shows where in the session the cost actually accrued.
```

If the README has no list of scripts (only prose), insert a one-sentence reference matching the prose style.

- [x] **Step 3: Commit**

```
git add README.md
git commit -m "readme: mention plot-session.py"
```

---

### Task 10: End-to-end cross-validation

**Files:**
- (No file changes — verification only)

- [ ] **Step 1: Run the full retrospective flow end-to-end**

```
python scripts/analyze-month.py ~/.claude/projects --month 2026-04 --label chonkers --out reports
python scripts/summarize.py
```

Sanity-check the printed totals are sensible.

- [ ] **Step 2: Pick a top-3 session from `summarize.py` output and plot it**

From the "TOP 20 SESSIONS" stdout, pick a session with high cost AND non-trivial subagent count. Note its 8-char prefix and its `Raw $` value.

```
python scripts/plot-session.py <prefix> --open
```

- [ ] **Step 3: Verify cumulative line endpoint matches sessions.csv**

Open `reports/sessions.csv`, find the row for that session. Compute the parent-only portion: `cost_usd - subagent_cost`. The chart's cumulative-line endpoint (top-right) should match this value to within rounding (~$0.0005).

If they match: the per-turn extraction and pricing path are correct end-to-end.
If they diverge: something is wrong. Most likely culprit is a dedup discrepancy between `iter_assistant_turns` and `process_file` in analyze-month.py — re-check those two should produce equivalent dedup behavior.

- [ ] **Step 4: Verify the page caption subagent stat matches sessions.csv**

The chart caption shows "Subagents: N dispatches, $X.XX aggregate". Compare to sessions.csv:
- `N` should match `subagent_count`.
- `$X.XX` should match `subagent_cost` to rounding.

- [ ] **Step 5: Verify --x time and --inline-js still work on this real session**

```
python scripts/plot-session.py <prefix> --x time --inline-js
```

Open the resulting HTML offline (turn off network briefly). Chart should render correctly with a wall-clock x-axis.

- [ ] **Step 6: No commit if everything passes**

If a divergence required a code fix, commit that fix with a clear message explaining what diverged and why. Otherwise nothing to commit at this step.
