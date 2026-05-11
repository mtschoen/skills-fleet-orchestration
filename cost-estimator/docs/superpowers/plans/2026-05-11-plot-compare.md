# plot-compare: period-over-period overlay chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `scripts/plot-compare.py` to the cost-estimator skill — a sibling of plot-trend.py that renders any window vs the same-length prior window as an overlaid Chart.js HTML page (grouped bars + twin cumulative lines).

**Architecture:** New script alongside plot-trend.py + plot-session.py. Bucket math, CSV reading, range parsing, and a new `parse_last("168h"|"7d")` shorthand parser plus a new `prior_window_for(start, end, *, mode)` helper all live in a new `scripts/trend_data.py` module that plot-trend.py and plot-compare.py both import. plot-compare.py always renders the overlay chart type — no flag switches chart kinds. Bucketing within each window is by bucket-index (Day 1, Day 2…) so paired bars are apples-to-apples wall-clock-relative slices, not calendar-aligned.

**Tech Stack:** Python 3.11+, Chart.js 4 (CDN via existing `chart_runtime.py`), argparse, csv stdlib.

**Conventions for this submodule** (established across the trend-graph and follow-up sessions):
- Separate commit per logical task. Plan tasks → roughly one commit each.
- Refactors that should be byte-identical use the regression-diff pattern (capture pre-edit HTML output to `/tmp`, apply edits, capture post-edit, `diff` should be empty).
- `python scripts/test_buckets.py` and `python scripts/test_resolve_roots.py` (or `bash scripts/run-tests.sh`) should pass after every code-touching task.
- Workdir is `C:/Users/mtsch/skills-dev/cost-estimator` (a git submodule of `~/skills-dev`).

---

## Phase 4: Docs + cleanup

### Task 7: Update SKILL.md + README.md

**Files:**
- Modify: `cost-estimator/SKILL.md` (add new step 7 after the plot-trend step; update Files list)
- Modify: `cost-estimator/README.md` (add "## Comparing two windows" section after "## Trend across sessions"; add `plot-compare.py` and `trend_data.py` to Files list)

- [x] **Step 1: Add step 7 to SKILL.md "Steps" section**

In `cost-estimator/SKILL.md`, after the existing step 6 (`Plot the aggregate trend across the range.`) and before step 7 (`Offer to save.`) — which means renumbering the old step 7 to 8:

```markdown
7. **Compare two windows side-by-side.** When the user asks "is my
   spend trending up/down?" or "how does this week compare to last?",
   render the period-over-period overlay:
   ```bash
   python <skill-root>/scripts/plot-compare.py \
       (--month YYYY-MM | --start YYYY-MM-DD --end YYYY-MM-DD | --last <Nh|Nd>) \
       [--bucket {day,week,month}] [--inline-js] [--open]
   ```
   The prior window is auto-derived as the same-length window
   immediately before the current one. Bucket-index (Day/Week/Month N)
   makes paired bars apples-to-apples wall-clock-relative slices, not
   calendar-aligned. Output lands in `<skill-root>/reports/compare-<range>.html`.
8. **Offer to save.** [renumbered from old step 7]
```

(Just renumber the old `7. **Offer to save.**` → `8. **Offer to save.**` — content unchanged.)

- [x] **Step 2: Add `plot-compare.py` + `trend_data.py` to SKILL.md Files list**

In `cost-estimator/SKILL.md` "Files in this skill" section, after `scripts/plot-trend.py`:

```markdown
- `scripts/plot-compare.py` — period-over-period overlay chart.
  Renders any window vs the same-length prior window (--month /
  --start+--end / --last). Imports bucket helpers from `trend_data.py`.
- `scripts/trend_data.py` — shared bucket math, CSV reader, and range
  parsers. Imported by plot-trend.py and plot-compare.py so the same
  bucketing logic stays in one place.
```

- [x] **Step 3: Add "## Comparing two windows" section to README.md**

In `cost-estimator/README.md`, after the existing `## Trend across sessions` section and before `## Files`, insert:

```markdown
## Comparing two windows

To check whether spend is trending up or down, render any window
against the same-length prior window:

```bash
python scripts/plot-compare.py --last 168h --open    # past 168h vs prior 168h
python scripts/plot-compare.py --month 2026-04 --open  # April vs March
```

The prior window is auto-derived (no second range to specify). The chart
shows grouped bars (current vs prior side by side) per bucket and twin
cumulative lines on a right axis. Bucket-index makes paired bars
apples-to-apples wall-clock-relative slices — Day 1 covers the first 24h
of each window, not the same calendar date.
```

- [x] **Step 4: Add `plot-compare.py` + `trend_data.py` to README Files list**

In `cost-estimator/README.md` `## Files` section, after the existing `scripts/plot-trend.py` entry:

```markdown
- `scripts/plot-compare.py` — render any window vs the same-length
  prior window as an overlay chart (grouped bars + twin cumulative
  lines). Uses bucket-index within each window so paired bars are
  apples-to-apples wall-clock-relative slices.
- `scripts/trend_data.py` — shared bucket math, CSV reader, and
  range parsers (month / range / duration). Imported by both
  `plot-trend.py` and `plot-compare.py`.
```

- [x] **Step 5: Commit**

```bash
git add SKILL.md README.md
git commit -m "docs: document plot-compare.py and trend_data.py

SKILL.md gets a new step 7 (period-over-period overlay) and Files
entries for plot-compare.py + trend_data.py. README.md gets a
'Comparing two windows' section parallel to 'Trend across sessions'
and the same Files-list additions. No screenshot in this delivery —
defer to user (same as the still-deferred trend-graph screenshot).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Delete the superseded one-off `compare-168h-plot.py`

**Files:**
- Delete: `~/skills-dev/.claude/scripts/compare-168h-plot.py`

NOTE: Keep `~/skills-dev/.claude/scripts/compare-168h.py` (the text-mode comparison sibling) — it has no replacement in this design; a text-comparison mode is a future feature.

- [ ] **Step 1: Remove the one-off HTML script**

```bash
rm C:/Users/mtsch/skills-dev/.claude/scripts/compare-168h-plot.py
ls C:/Users/mtsch/skills-dev/.claude/scripts/
```

Expected: `compare-168h.py` still present; `compare-168h-plot.py` gone.

- [ ] **Step 2: No commit at the cost-estimator submodule level**

The one-off lives in the parent `skills-dev` umbrella under `.claude/scripts/`, which is gitignored (or untracked, depending on user setup). Per `git status -uall` from the umbrella, `.claude/scripts/` typically isn't tracked. If it IS tracked at the umbrella, commit the deletion from the umbrella directory:

```bash
cd C:/Users/mtsch/skills-dev
git status .claude/scripts/   # check if tracked
# if tracked: git rm .claude/scripts/compare-168h-plot.py && git commit -m "..."
# if untracked: nothing to commit; the file is just gone
```

---

### Task 9: Final verification + cost-estimator close-out

**Files:**
- Modify: `cost-estimator/docs/superpowers/plans/2026-05-11-plot-compare.md` (delete)

- [ ] **Step 1: Run all tests one last time**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
bash scripts/run-tests.sh
```

Expected: all three test files print `OK`, `All tests passed.`

- [ ] **Step 2: Regression-smoke plot-trend.py one last time**

```bash
python scripts/plot-trend.py --month 2026-04 --out /tmp/trend-final.html
grep -o 'Total: \$[0-9.]*' /tmp/trend-final.html
```

Expected: same total as recorded during Task 1 Step 5 (or close to it; CSV may have grown between runs).

- [ ] **Step 3: Smoke plot-compare.py one last time**

```bash
python scripts/plot-compare.py --last 168h --out /tmp/compare-final.html
grep -c "Cost comparison" /tmp/compare-final.html
```

Expected: HTML written, contains the template.

- [ ] **Step 4: Delete this plan file**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
git rm docs/superpowers/plans/2026-05-11-plot-compare.md
git commit -m "plot-compare: remove plan after feature ship

All 9 tasks complete: trend_data.py extraction, parse_last +
prior_window_for helpers, plot-compare.py skeleton + rendering, docs,
and one-off cleanup. Design rationale folded into SKILL.md / README.md
/ inline comments per the superpowers convention.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Bump skills-dev umbrella pointer**

```bash
cd C:/Users/mtsch/skills-dev
git add cost-estimator
git commit -m "bump: cost-estimator -> $(git -C cost-estimator rev-parse --short HEAD) (plot-compare PoP overlay)

Adds plot-compare.py for period-over-period overlay charts. New
trend_data.py module shares bucket math, CSV reader, and range
parsing between plot-trend.py and plot-compare.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Push to both hosts**

```bash
cd C:/Users/mtsch/skills-dev
cmd.exe /c "scripts\\push-all.bat"
```

Or, on a non-Windows host, `bash scripts/push-all.sh`.

Expected: all submodules either `up-to-date` or freshly pushed; `cost-estimator` shows new commits pushed to both `origin` (Gitea) and `github`; `skills-dev (index)` likewise. Summary line reads `All pushes succeeded or already up-to-date.`
