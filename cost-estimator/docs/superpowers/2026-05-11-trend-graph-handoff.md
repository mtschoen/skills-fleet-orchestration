# Aggregate trend graph — session handoff

**Date written:** 2026-05-11
**Parent session:** brainstorm → spec → plan → 10-task subagent-driven implementation
**Purpose:** dump everything the next session needs so we don't re-derive context. Verbose by design.

---

## TL;DR

The aggregate cost-trend chart feature is **functionally complete and shippable** on the `cost-estimator` submodule's `main` branch. All 10 implementation tasks landed across 16 commits. Cross-validation passes: `plot-trend.py --month 2026-04` headline `$3712.8966` matches `summarize.py` headline `$3712.90` exactly (different decimal precision, same value).

The final reviewer flagged **3 High-priority polish items** and a handful of Medium/Low items. None are correctness bugs. The user wants to pick these up in a fresh session to save context budget — this doc is the handoff.

---

## What was built

A new aggregate cost-trend chart for the `cost-estimator` skill, plus `CLAUDE_COST_ROOTS` env-var support so multi-machine setups don't have to repeat CLI args. Closes the "Trend over time beyond daily" gap that was explicitly noted in the old SKILL.md.

User workflow now:

```bash
# Optionally set once per machine in shell profile:
export CLAUDE_COST_ROOTS="chonkers:C:/Users/mtsch/.claude/projects,llamabox:Y:/.claude/projects"

# Then any month:
python scripts/analyze-month.py --month 2026-04   # writes reports/sessions.csv
python scripts/plot-trend.py --month 2026-04 --open
```

Stacked bars per machine label, right-axis cumulative line, auto-picked bucket granularity (≤14d→day, ≤90d→week, >90d→month) with `--bucket` override.

---

## Commit topology (cost-estimator submodule)

Base of feature: `bda2034` (last commit before this work — "chore: sanitize personal hostnames/usernames")
Head of feature: `9fe0881` ("readme: document plot-trend.py and CLAUDE_COST_ROOTS")

The 16 commits in order:

```
9fe0881 readme: document plot-trend.py and CLAUDE_COST_ROOTS                    (Task 10)
6e7cedc skill: document plot-trend.py and CLAUDE_COST_ROOTS                     (Task 9)
f45bca4 plot-trend: CLI wiring, range bounds, end-to-end smoke passes           (Task 8)
e2c12ba plot-trend: HTML template, Chart.js config, stable label colors        (Task 7)
6b5fb2f plan: document NAIVE-boundary contract for read_sessions_in_range      (plan sync)
30bf789 plot-trend: CSV range filter and per-label pivot                       (Task 6)
cc0b295 plan: switch Task 5 month bucket key to %Y-%m for sortability          (plan sync)
53aa348 plot-trend: bucket_key + auto_bucket with unit smoke                   (Task 5)
acb40f1 analyze-month: use _resolve_roots() for CLI+env-var root resolution    (Task 4)
8ec2b56 analyze-month: add _resolve_roots() with CLAUDE_COST_ROOTS support     (Task 3)
b66ad8c task 2 followup: drop incorrect noqa annotations and sync plan template (Task 2 fix)
f741fd1 plot-session: route Chart.js script tags through chart_runtime          (Task 2)
596bcbb plan: align Task 2 import with cached_download rename                  (plan sync)
793ea6b chart_runtime: shared Chart.js URL constants + script-tag helper        (Task 1, amended)
565d6b2 plan: aggregate trend graph (consume spec)                              (plan)
6fcf418 spec: aggregate trend graph design                                      (spec)
```

The plan and spec commits are the brainstorm-to-plan handoff. The spec was consumed (deleted) when the plan was written. The plan still exists at `docs/superpowers/plans/2026-05-10-aggregate-trend-graph.md` and will be deleted at branch-finish (per `superpowers:finishing-a-development-branch`).

---

## Current operational state

- **Working directory:** `C:/Users/mtsch/skills-dev/cost-estimator` (this is a git submodule of `~/skills-dev`)
- **Branch:** `main` (user explicitly chose main + no worktree at start of execution — "Main, no worktrees" answer to the AskUserQuestion)
- **Tree:** clean (verified — all commits landed, no in-flight edits)
- **`skills-dev` umbrella pointer:** NOT yet bumped. The skills-dev repo still points at the pre-feature `cost-estimator` commit. Bumping it is part of branch-finish. The user has `scripts/push-all.{sh,bat}` for syncing both Gitea and GitHub.
- **Permissions:** global `~/.claude/settings.json` has `Bash(*)` + `Edit(**)` — no permission gating issues for subagents.

---

## Cross-validation evidence (don't lose this)

Verified by Task 8's implementer AND independently re-verified by the plan-compliance reviewer:

- `python scripts/summarize.py` headline `local total $ 3712.90` (TOTAL row)
- `python scripts/plot-trend.py --month 2026-04 --out /tmp/...` HTML meta-row `Total: $3712.8966`
- `grep -o 'Total: \$[0-9.]*' /tmp/april.html` → `Total: $3712.8966`

Same value at different decimal precision. This is the strongest evidence that the data flow (JSONL → analyze-month CSV → plot-trend chart) preserves totals correctly. If this number stops matching in the future, the math drifted somewhere.

---

## File inventory

### New files
| Path | Lines | Purpose |
|------|-------|---------|
| `scripts/chart_runtime.py` | ~80 | Chart.js URL/version constants, `cached_download()`, `chartjs_script_tags(inline, want_time_adapter)` |
| `scripts/plot-trend.py` | ~430 | Full CLI tool. Bucket math, CSV reader, pivot, HTML render, main() |
| `scripts/test_buckets.py` | ~65 | 5 tests for `bucket_key` (day/week/month/ISO-year-boundary) + `auto_bucket` thresholds |
| `scripts/test_resolve_roots.py` | ~80 | 5 tests for env-var parsing precedence (incl. Windows `C:` drive case) |

### Modified files
| Path | Change |
|------|--------|
| `scripts/plot-session.py` | Imports from `chart_runtime` instead of holding own copies. Regression-verified byte-identical HTML output. |
| `scripts/analyze-month.py` | `_resolve_roots()` helper added, `CLAUDE_COST_ROOTS` env var wired through main(), `nargs="*"` for env-only invocations, pre-worker `path.exists()` validation |
| `SKILL.md` | Gap bullet dropped, new step 6 for `plot-trend.py`, `CLAUDE_COST_ROOTS` documented in inputs section, files-list updated |
| `README.md` | New `## Trend across sessions` section after the per-session section |

### Doc artifact still present
- `docs/superpowers/plans/2026-05-10-aggregate-trend-graph.md` — the 10-task plan. All checkboxes flipped to `- [x]`. Will be deleted at branch-finish (per skill convention — durable insight folds into SKILL.md/README/code).

---

## Test commands (for quick re-verification in next session)

From `C:/Users/mtsch/skills-dev/cost-estimator`:

```bash
# Unit tests — both should print "OK"
python scripts/test_buckets.py
python scripts/test_resolve_roots.py

# Cross-validation — these numbers must match
python scripts/analyze-month.py --month 2026-04        # regenerates reports/sessions.csv
python scripts/summarize.py | grep -i total            # gets summarize's headline
python scripts/plot-trend.py --month 2026-04 --out /tmp/verify.html
grep -o 'Total: \$[0-9.]*' /tmp/verify.html            # should be $3712.8966
```

Empty-range check:
```bash
python scripts/plot-trend.py --start 2099-01-01 --end 2099-01-31
# Expect: exit 1, stderr "csv has N rows total, span ..."
```

Missing CSV check:
```bash
python scripts/plot-trend.py --month 2026-04 --csv C:/nonexistent/sessions.csv
# Expect: exit 1, "error: sessions.csv not found at ..."
```

Env-var smoke (PowerShell):
```powershell
$env:CLAUDE_COST_ROOTS = "local:C:/Users/mtsch/.claude/projects"
python scripts/analyze-month.py --month 2026-04
# Expect: [local] C:\Users\mtsch\.claude\projects: N jsonl files
```

---

## High-priority follow-up items (the next session's job)

These are the cleanups the final reviewer flagged. None are correctness bugs — all are polish/UX. Estimated total: ~35 min.

### I-1: Drop dead `chartjs_inline_bytes`/`time_adapter_inline_bytes` params in `plot-session.py`

**Why this exists:** Task 2 (the chart_runtime extraction refactor) kept these params "surgical for the regression diff" — the plan explicitly said:

> The `chartjs_inline_bytes` / `time_adapter_inline_bytes` parameters on `render_html` are now unused. Keep them in the signature (and the `main()` call site) so this task's diff stays surgical; remove in a follow-up if desired.

That diff has long since passed its regression check (byte-identical output verified at commit `f741fd1`). Carrying the dead-weight forward makes the next reader trace what they do.

**What's actually dead:**
- `time_adapter_inline_bytes` parameter — passed in but **never read** inside `render_html` after the refactor.
- `chartjs_inline_bytes` parameter — only consulted as a bool sentinel via `chartjs_inline_bytes is not None`. Equivalent to just passing `arguments.inline_js`.
- The download orchestration in `main()` (roughly lines 290-301 per the reviewer) pre-warms a cache that `chartjs_script_tags()` reads again internally — pure double-work. The cache hit makes it harmless, but it's still dead.

**Concrete change:**
1. In `scripts/plot-session.py` `render_html` signature: drop `chartjs_inline_bytes` and `time_adapter_inline_bytes` kwargs.
2. Replace `chartjs_inline_bytes is not None` with a new `inline: bool` param (and update the call site in `main()` to pass `inline=arguments.inline_js`).
3. Delete the `chartjs_bytes = cached_download(...)` and `time_adapter_bytes = cached_download(...)` pre-warm block in `main()` — `chartjs_script_tags(inline=True, ...)` handles it.
4. Re-run the regression test from Task 2 to confirm byte-identical output:
   ```bash
   cd C:/Users/mtsch/skills-dev/cost-estimator/scripts
   # Pick any session id from ~/.claude/projects/...
   python plot-session.py <session-id> --out /tmp/before-cleanup.html
   # (apply the I-1 edits)
   python plot-session.py <session-id> --out /tmp/after-cleanup.html
   diff /tmp/before-cleanup.html /tmp/after-cleanup.html   # should be empty
   ```
5. Same with `--inline-js` to verify that path works:
   ```bash
   python plot-session.py <session-id> --inline-js --out /tmp/after-inline.html
   ```

**Commit message suggestion:** `plot-session: drop dead chartjs/time-adapter bytes params after chart_runtime extraction`

### I-2: Friendly errors for malformed `--month`

**Where:** Both `scripts/plot-trend.py` (`_month_bounds`) and `scripts/analyze-month.py` (`month_bounds`, around line 184-193 per the reviewer).

**Current behavior (verified by the reviewer):**
- `python scripts/plot-trend.py --month banana` → `ValueError: invalid literal for int() with base 10: 'banana'` traceback
- `python scripts/plot-trend.py --month 2026-13` → `ValueError: month must be in 1..12` traceback
- `python scripts/plot-trend.py --month 2026-04-15` → `ValueError: too many values to unpack` traceback

**Concrete change:**

In `plot-trend.py`, wrap the body of `_month_bounds` (or its caller in `main()`):

```python
if arguments.month:
    try:
        range_start, range_end = _month_bounds(arguments.month)
    except ValueError as exc:
        parser.error(f"--month: {exc} (expected YYYY-MM)")
```

Mirror the same shape in `analyze-month.py`'s `main()`.

Or alternative: validate via regex up front in `_month_bounds`:

```python
import re
if not re.fullmatch(r"\d{4}-\d{2}", month_string):
    raise ValueError(f"expected YYYY-MM, got {month_string!r}")
```

Either works. Per-call-site try/except is more flexible because the same `_month_bounds` is reusable; regex inside `_month_bounds` makes the helper self-validating.

**Commit message suggestion:** `plot-trend/analyze-month: friendly error on malformed --month`

### I-3: Reject `--month X --end Y` instead of silently ignoring `--end`

**Why this slips through:** The argparse mutex group covers `--month` vs `--start` (because `--start` is in the group), but `--end` is declared OUTSIDE the group as a free-floating flag. So `--month 2026-04 --end 2026-04-15` parses successfully and `main()` happily ignores `--end`. Silent flag-ignoring is the bad kind of surprise.

**Concrete change:** Add a post-parse manual check in both `plot-trend.py` `main()` and `analyze-month.py` `main()`:

```python
if arguments.month and arguments.end:
    parser.error("--end requires --start, not --month")
```

Place this right after `arguments = parser.parse_args()` and before the `if arguments.month:` branch.

Verify:
```bash
python scripts/plot-trend.py --month 2026-04 --end 2026-04-15
# Expect: exit 2, "error: --end requires --start, not --month"
```

**Commit message suggestion:** `plot-trend/analyze-month: reject --month + --end combo instead of silently ignoring --end`

---

## Medium-priority items

### M-1: Two genuinely unused noqa imports in `plot-session.py`

These get cleaned up automatically if you do I-1, because the entire import block shrinks. If you DON'T do I-1:

- `CHARTJS_CDN_URL` (currently imported with `# noqa: F401  (re-exported for symmetry; chart_runtime uses it)`)
- `TIME_ADAPTER_CDN_URL` (same)

Both genuinely unused in `plot-session.py`. The "re-exported for symmetry" rationale is wrong — `chart_runtime` uses its own constants internally regardless of whether plot-session imports them. Just delete those two lines.

### README "Files" list addition

The README's `## Files` section (around line 52-64) lists `plot-session.py` but never adds `plot-trend.py` or `chart_runtime.py`. The README body documents them (in the new `## Trend across sessions` section), but the file list is stale. ~2 minutes to fix.

### Comment-on-cumulative-loop-precision

`pivot_to_datasets` in `plot-trend.py` has a cumulative loop that LOOKS like an O(B × L) inefficiency:

```python
cumulative = []
running = 0.0
for bucket in buckets_sorted:
    for label in labels_sorted:
        running += sums[label].get(bucket, 0.0)
    cumulative.append(round(running, 4))
```

This is **NOT a bug and SHOULD NOT be "optimized."** The reason: summing from raw `sums[label][bucket]` (unrounded) and rounding only the final cumulative value preserves precision. Switching to `sum(per_label_costs[label][index] for label in labels)` would accumulate ~1¢ of round-down error per bucket. The final reviewer initially flagged this as cleanup but reversed on second look. A one-line comment would save future readers the same trace:

```python
cumulative = []
running = 0.0
# Sum from unrounded sums[] to avoid per-bucket round-down accumulation
# (per_label_costs values are already rounded to 4dp — using them here would
#  drift over many buckets).
for bucket in buckets_sorted:
    for label in labels_sorted:
        running += sums[label].get(bucket, 0.0)
    cumulative.append(round(running, 4))
```

---

## Low-priority items (worth tracking, not urgent)

### M-2: No-spend buckets excluded from x-axis (design decision)

`pivot_to_datasets` builds `bucket_set` from `bucket_key(row[...])` only on rows that exist in the filtered range. Days where no sessions ran don't appear on the chart. Visual consequence:

- Daily chart for April 2026 has 22 bars (active days) instead of 30 (calendar days) — verified by the smoke run.
- Bars are evenly spaced rather than calendar-grid-aligned.
- Cumulative line looks steeper than reality (no plateau across silent days).

The fix is mechanical (generate the full bucket sequence from `range_start..range_end` at the chosen granularity, pass it into `pivot_to_datasets`, zero-fill missing buckets). But it changes the chart's data semantics, so it's a deliberate design call rather than a drive-by.

**Recommendation:** defer until the user sees the chart and decides which they prefer. Calendar-accurate is more honest for sparse data; data-presence is denser and easier to read.

If chosen, the implementation outline:
1. Add `enumerate_buckets(range_start, range_end, granularity) -> list[str]` helper to `plot-trend.py`.
2. Add optional `bucket_axis: list[str] | None` parameter to `pivot_to_datasets`. When provided, use it as `buckets_sorted`; when None, fall back to current data-presence behavior.
3. In `main()`, call `enumerate_buckets` and pass the result to `pivot_to_datasets`.

### M-6: Test runner script

`test_buckets.py` and `test_resolve_roots.py` are runnable as `python <file>` but no orchestrator. A simple `scripts/run-tests.{sh,bat}` (or `.ps1`) that runs both and exits non-zero on failure would close the safety net. ~10 minutes.

### M-7: Palette wraparound docstring note

`_label_color` in `plot-trend.py` uses an 8-color palette with `digest[0] % 8` — collisions at 9+ labels. Currently fine for the user's 2-machine setup. Add a one-line docstring note ("consumers with >8 distinct labels may see color collisions; pick visually distinct labels in that case"). ~1 minute.

---

## Don't-touch list (known non-issues that LOOK like bugs)

1. **`pivot_to_datasets`'s cumulative loop appearing O(B × L).** It's correct as-is for precision reasons. See M-3 above.

2. **`plot-trend.py` is ~430 lines, near the user's 500-line soft cap.** Don't split it — about 90 of those lines are the embedded `HTML_TEMPLATE` (data, not code). The actual Python is ~340 lines across four logical sections (bucket math, CSV reader, pivot, render+main). Reads top-to-bottom cleanly.

3. **`(no parseable rows)` empty-range branch is theoretically reachable but not smoke-tested.** Only fires if `read_sessions_in_range` returned zero rows AND every row in the CSV has empty/unparseable `first_timestamp`. With `analyze-month.py` as the only writer, that combination shouldn't occur. Single-line fallback with obvious behavior.

4. **`render_html`'s `total_cost = cumulative[-1] if cumulative else 0.0` guard is dead but harmless.** `render_html` is only reached after `main()` errored out on empty rows (the "no sessions in range" exit). The empty-case guard is defensive and worth keeping for robustness.

5. **The plan file (`docs/superpowers/plans/2026-05-10-aggregate-trend-graph.md`) still exists.** Per the writing-plans skill convention, it gets deleted at branch-finish, not before. Each task's checkboxes are all flipped to `- [x]`. The plan has ~1230 lines of working scaffolding that should fold into SKILL.md / README.md / inline comments before deletion — but most of that distillation already happened (the plan's design rationale lives in SKILL.md's step 6 and the README's new section, and the test cases live in the test files).

---

## Design decisions worth preserving (folded notes)

These came up during the build and might be useful if the feature ever gets revised:

### Why `"%Y-%m"` and not `"%Y-%b"` for the month bucket key

Lexical sort order. `"2026-Apr"` < `"2026-Aug"` < `"2026-Dec"` < `"2026-Feb"` alphabetically — would mis-order the x-axis when a range spans multiple months within a year. The reviewer caught this on Task 5; fix landed in commit `cc0b295`. Documented in the `bucket_key` docstring. Display formatting (if "Apr 2026" is wanted visually) should happen at render time, not in the key.

### Why `partition(":")` and not `split(":")` for env-var parsing

Windows paths like `C:/Users/mtsch/.claude/projects` contain a colon (drive letter). `partition(":")` splits on the FIRST colon and keeps the rest as the path. `split(":")` would mangle the path. `test_windows_drive_letter_in_env_path` in `test_resolve_roots.py` pins this behavior.

### Why `read_sessions_in_range` strips tzinfo from CSV timestamps

The CSV stores tz-aware ISO timestamps (`+00:00`). `argparse`-parsed `--month 2026-04` and `--start 2026-04-01` produce NAIVE datetimes. Comparing naive vs aware datetimes raises `TypeError`. Stripping tzinfo at parse time (in the reader, not the caller) lets callers pass naive boundaries without thinking about it. Documented in the docstring.

### Why a single `chart_runtime.py` module instead of separate runtimes per plotter

Chart.js version constants MUST stay in sync across plotters when Chart.js updates. The download cache and the `<script>`-tag builder are mechanical enough that duplicating them invites drift. The 80-line `chart_runtime.py` is the smallest unit that captures "things that would literally duplicate." HTML templates, chart configs, and metadata row content stay in each plotter — those legitimately differ.

### Why category x-axis instead of time x-axis

Chart.js has a known sparsity gotcha when stacking bars on a time-scale axis (issue chartjs/Chart.js#2868 and friends). Stacked bars on a `type: 'time'` axis with uneven intervals produce overlapping bars. Category axis with lexically-sortable bucket keys (see month-key decision above) sidesteps the issue and reads cleaner for bucketed data.

### Why TDD for `_resolve_roots` and `bucket_key` but not `render_html`

Pure functions with edge cases (ISO week year boundary, Windows drive letters, env-var precedence) benefit hugely from unit tests. HTML rendering tests-by-eye via `--open` plus a `python -c "ast.parse(...)"` sanity check is more practical than a snapshot-based HTML test that would be brittle to Chart.js version bumps.

---

## What was learned about the workflow (for future executions)

1. **Plan-template race condition with implementer amends.** When you edit the plan file in parallel with an implementer's `git commit --amend --no-edit`, the implementer's amend can accidentally fold into the wrong commit (yours instead of theirs). Hit this between Task 1's noqa fix and the plan template update. Workaround: amend the resulting commit's message to describe BOTH changes (which is what happened in `b66ad8c`).

2. **DONE_WITH_CONCERNS means "address before review."** Task 6's implementer correctly flagged the tz mismatch as a concern. Best to fix before plan-review rather than ratifying the concern. Pattern that worked: amend implementer's commit + sync plan template in parallel, then re-review.

3. **Code-quality reviewer catches what plan-compliance reviewer doesn't.** Plan-compliance is checking "did you build what was asked?" Code-quality is checking "is what you built well-built?" Both catch different things. Skipping code-quality on the doc tasks (9, 10) was fine; on code tasks, both reviewers earned their keep.

4. **`# noqa: F401` cargo-culting is a real risk.** Task 2 inherited a plan template with four `noqa: F401` decorations, two of which were factually wrong (the names ARE used in `main()`). The code-quality reviewer caught it; same mistake would have propagated to Task 7's `plot-trend.py` if not fixed. The mistake was in the original plan I wrote — now corrected.

5. **Doc-only tasks don't need both reviews.** Tasks 9 and 10 (SKILL.md, README.md) only got plan-compliance review (the reviewer read the full doc in context and confirmed it reads coherently — the equivalent of a code-quality pass for prose). Skipped formal `superpowers:code-reviewer` for those, which would have had little to chew on.

---

## Subagent IDs (probably not useful in new session, listing for completeness)

These are the implementer agents that built each task. They could theoretically be resumed via `SendMessage` if context were preserved, but new sessions start fresh anyway. Listed only for audit trail:

- Task 1: `a7fc4ee252d9a52d5` (chart_runtime.py, including the rename amend)
- Task 2: `a54b3cfc256034a37` (plot-session.py refactor, including noqa fix amend)
- Task 3: `ad90d0ec71c670fc8` (_resolve_roots helper + tests)
- Task 4: `a3bc2b2c58166ba0f` (analyze-month main() wiring)
- Task 5: `a5cd29c8e4b62490e` (bucket_key + auto_bucket, including %Y-%m amend)
- Task 6: `a88d0bb1d3f1a97b3` (CSV reader + pivot, including tz-strip amend)
- Task 7: `a9b482c309778b885` (HTML render)
- Task 8: `ad7595fa364cdcfa3` (CLI + e2e smoke)
- Task 9: `a5e931ca30ccdf535` (SKILL.md)
- Task 10: `a560a385d99e66685` (README.md)

---

## When all follow-ups land, branch-finish steps

These are the steps to fully close out the feature once I-1, I-2, I-3 (and any chosen Medium/Low items) are in:

1. Run all unit tests one more time:
   ```bash
   python scripts/test_buckets.py
   python scripts/test_resolve_roots.py
   ```
2. Re-run cross-validation:
   ```bash
   python scripts/analyze-month.py --month 2026-04
   python scripts/summarize.py | grep -i total
   python scripts/plot-trend.py --month 2026-04 --out /tmp/final.html
   grep -o 'Total: \$[0-9.]*' /tmp/final.html
   ```
   Both numbers should still be `$3712.90` / `$3712.8966`. If they diverged, something broke during the cleanups.
3. Delete the plan file:
   ```bash
   git rm docs/superpowers/plans/2026-05-10-aggregate-trend-graph.md
   git rm docs/superpowers/2026-05-11-trend-graph-handoff.md  # (this file)
   git commit -m "trend-graph: remove plan + handoff after feature ship"
   ```
4. Bump the `skills-dev` umbrella's submodule pointer:
   ```bash
   cd C:/Users/mtsch/skills-dev
   git add cost-estimator
   git commit -m "bump: cost-estimator -> <head sha> (aggregate trend graph + CLAUDE_COST_ROOTS)"
   ```
5. Push everything:
   ```bash
   # In skills-dev:
   ./scripts/push-all.{sh,bat}
   ```
   This pushes both submodule and umbrella to Gitea + GitHub.

OR alternatively, run `superpowers:finishing-a-development-branch` and let it walk you through.

---

## Open follow-up: a screenshot for the README

The plan called for embedding a sample trend-chart screenshot in the README "Trend across sessions" section, parallel to how `plot-session.py`'s README section has `screenshot.png`. Task 10 deferred the screenshot ("Don't add a screenshot yet — that'll come after the first real run as a follow-up"). The screenshot should be generated from a real run of `plot-trend.py --month <some-month> --open`, captured manually, saved to `screenshot-trend.png` (or similar), and the README updated to embed it. ~5 minutes of UI work, deferred to the user.

---

End of handoff. Pick up in a fresh session — the I-1/I-2/I-3 cleanups should take ~35 minutes total.
