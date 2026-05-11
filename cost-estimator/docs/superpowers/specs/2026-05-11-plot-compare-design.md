# plot-compare: period-over-period overlay chart

**Date:** 2026-05-11
**Status:** Draft for plan handoff
**Scope:** Add a new `plot-compare.py` script to the cost-estimator skill, plus a small refactor extracting shared range/bucket helpers into a `trend_data.py` module.

---

## Goal

Add an overlay-chart feature that answers "is my spend accelerating?" by comparing any window to the same-length prior window — the period-over-period (PoP) pattern that's standard in BI tools (Domo, Metabase, Sigma, Holistics). Generalizes the one-off `compare-168h-plot.py` script (which lives in `~/skills-dev/.claude/scripts/`) into a reusable cost-estimator tool.

Closes one of the gaps explicitly noted in the current SKILL.md "What this skill does not do (yet)" section: **"Trend over time beyond daily. No weekly / month-over-month deltas."**

---

## User stories

1. *"What's my spend trend this week vs last week?"* → `python scripts/plot-compare.py --last 7d --open`
2. *"How did April compare to March?"* → `python scripts/plot-compare.py --month 2026-04 --open`
3. *"Compare release week to the week before."* → `python scripts/plot-compare.py --start 2026-04-15 --end 2026-04-21 --open`

All three produce an HTML chart with grouped bars (current vs prior, side by side) and twin cumulative lines.

---

## CLI surface

```
python scripts/plot-compare.py
    (--month YYYY-MM | --start YYYY-MM-DD --end YYYY-MM-DD | --last <Nh|Nd>)
    [--bucket {day,week,month}]   # default: auto from window length
    [--csv <path>]                # default: <skill-root>/reports/sessions.csv
    [--inline-js]
    [--out <path>]                # default: <skill-root>/reports/compare-<range>.html
    [--open]
```

**Mutually-exclusive group:** `--month`, `--start`, `--last`. `--end` requires `--start` (mirrored from plot-trend.py, including the `--month + --end` rejection from I-3).

**`--last` grammar:** Accept `<digits><h|d>` only — e.g., `168h`, `7d`, `30d`. Weeks/months deferred per YAGNI. Reject other suffixes with a clean `parser.error()`.

**`--last` anchor:** "now" at parse time (UTC). The current window is `[now - duration, now)`. The prior window is `[now - 2*duration, now - duration)`.

**Prior-window derivation** (all three modes):

| Mode | current window | prior window |
|---|---|---|
| `--month YYYY-MM` | [first second of month, last second of month] | same shape for prior month (handle Dec→Jan year rollover) |
| `--start S --end E` | [S 00:00, E 23:59:59] | duration = E-S+1day; prior = [S-duration, S - 1 second] |
| `--last 168h` | [now-168h, now) | [now-336h, now-168h) |

---

## Bucketing

Reuse `auto_bucket` + `bucket_key` from `trend_data.py` (extracted from plot-trend.py). Same thresholds: ≤14d → day, ≤90d → week, >90d → month.

**Key semantic difference from plot-trend.py:** plot-compare buckets by **"bucket-index within window"** (0..N-1), not by calendar date. So paired buckets cover the same wall-clock-relative slice in each window — true apples-to-apples comparison instead of calendar-aligned (which would put the prior window's data points on the past window's dates).

Concretely, for a `--last 168h` invocation with daily bucketing:
- Bucket 0 = first 24h of each window
- Bucket 6 = last 24h of each window

This was validated by the one-off script (see `~/skills-dev/.claude/scripts/compare-168h-plot.py`).

Bucket labels in the chart are like `"Day 1 (Mon 05-04 / Mon 04-27)"` — showing both windows' dates for that bucket-index, so the user can recover absolute dates from the visual.

---

## Chart spec

Single Chart.js mixed bar + line chart:

- **Bars** (left y-axis, "Per-bucket cost ($)"):
  - Current window: solid blue (`rgba(54, 162, 235, 0.85)`)
  - Prior window: solid gray (`rgba(150, 150, 150, 0.75)`)
  - Grouped (not stacked) so bars sit side by side per bucket
- **Lines** (right y-axis, "Cumulative cost ($)"):
  - Current window: solid blue, 2px
  - Prior window: dashed gray (`borderDash: [6, 4]`), 2px
- **Tooltip:** `mode: index, intersect: false` so hovering a bucket shows all four series values
- **Caption:** `current: start..end ($total / N sessions)` and same for prior

Both colors hardcoded — only ever two series, so the palette-collision concern from `_label_color` doesn't apply.

---

## Refactor: extract `trend_data.py`

Move from `plot-trend.py` into a new `cost-estimator/scripts/trend_data.py`:

- `bucket_key(timestamp, granularity)`
- `auto_bucket(days)`
- `read_sessions_in_range(csv_path, range_start, range_end)`
- `_month_bounds(month_string)` — rename to `month_bounds` (drop the leading underscore now that it's a public helper)
- `_date_bounds(start_string, end_string)` — rename to `date_bounds`

**Stays in plot-trend.py:**
- `pivot_to_datasets` (only stacked-trend needs label pivoting)
- `_label_color`, `PALETTE`
- `HTML_TEMPLATE`, `render_html`
- `main()`

After the move plot-trend.py drops from ~430 → ~360 lines; plot-compare.py is new at ~250 lines.

**Import shape:**
```python
from trend_data import (
    bucket_key, auto_bucket, read_sessions_in_range,
    month_bounds, date_bounds,
)
```

The existing `test_buckets.py` tests for `bucket_key` and `auto_bucket` get their import path updated.

---

## New `prior_window_for` helper

Single helper in `trend_data.py` that all three CLI modes converge on:

```python
def prior_window_for(
    current_start: datetime, current_end: datetime, *,
    mode: str,  # "month" | "range" | "duration"
) -> tuple[datetime, datetime]:
    """Return (prior_start, prior_end) for the window immediately
    before [current_start, current_end].

    - mode="month": prior is the calendar month before current_start
      (handles Dec->Jan year rollover via month_bounds).
    - mode="range": prior duration = current_end - current_start;
      prior = [current_start - duration, current_start - 1 second].
    - mode="duration": same shape as "range" — prior = [current_start
      - (current_end - current_start), current_start).
    """
```

The "range" vs "duration" distinction is end-inclusivity: `--start/--end` is inclusive (end at 23:59:59), so the prior end is 1 second before current_start. `--last` is half-open (end is "now" exclusive), so the prior end equals current_start exactly.

## New `--last` parser

```python
def parse_last(value: str) -> timedelta:
    """Parse '168h' or '7d' into a timedelta. Raises ValueError on malformed."""
    if not value or not value[:-1].isdigit():
        raise ValueError(f"--last must be <digits>(h|d), got {value!r}")
    suffix = value[-1]
    quantity = int(value[:-1])
    if quantity <= 0:
        raise ValueError(f"--last must be positive, got {value!r}")
    if suffix == "h":
        return timedelta(hours=quantity)
    if suffix == "d":
        return timedelta(days=quantity)
    raise ValueError(f"--last suffix must be 'h' or 'd', got {value!r}")
```

Lives in `trend_data.py` next to the other range helpers so plot-trend.py can adopt `--last` later without code movement.

---

## Tests

Add to `cost-estimator/scripts/test_buckets.py`:

1. `test_parse_last_hours` — `parse_last("168h") == timedelta(hours=168)`
2. `test_parse_last_days` — `parse_last("7d") == timedelta(days=7)`
3. `test_parse_last_rejects_bad_suffix` — `parse_last("4w")` raises ValueError
4. `test_parse_last_rejects_non_digit` — `parse_last("abc168h")` raises ValueError
5. `test_parse_last_rejects_zero_or_negative` — `parse_last("0d")` and `parse_last("-1h")` raise ValueError

Add to `cost-estimator/scripts/test_compare.py` (new):

6. `test_prior_window_for_month` — given `(2026-04-01, 2026-04-30 23:59:59)`, prior = `(2026-03-01, 2026-03-31 23:59:59)`
7. `test_prior_window_for_month_year_rollover` — given `(2026-01-01, 2026-01-31 23:59:59)`, prior = `(2025-12-01, 2025-12-31 23:59:59)`
8. `test_prior_window_for_arbitrary_range` — given `(2026-04-15, 2026-04-21 23:59:59)`, prior = `(2026-04-08, 2026-04-14 23:59:59)`
9. `test_bucket_by_index_within_window` — given two timestamps separated by 36h with `--bucket day`, bucket indices are [0, 1]

---

## Docs

Update files:

1. `README.md`: add a "## Comparing two windows" section after "## Trend across sessions". Mirror the existing "## Trend across sessions" structure (intro paragraph + code block + chart-style description).
2. `SKILL.md`: add a new step 7 (after the per-session-plot step) documenting `plot-compare.py`. Update the "What this skill does not do (yet)" section to drop the "no weekly / month-over-month deltas" bullet.
3. `README.md` Files list: add `scripts/plot-compare.py` and `scripts/trend_data.py`.

No screenshot in this delivery — defer to the user, parallel to the still-deferred trend-graph screenshot.

---

## Cross-validation

The one-off script's totals (`past=$2,151.37`, `prior=$1,172.99` as of 2026-05-11 09:30 UTC) become the regression baseline. After implementation, `plot-compare.py --last 168h` should produce the same totals (modulo "now" drifting). For a stable baseline that doesn't depend on wall-clock, the implementation plan should include a smoke command using `--month 2026-04` (compared to March 2026) whose totals can be cross-validated against `summarize.py --start 2026-03-01 --end 2026-03-31` and `--start 2026-04-01 --end 2026-04-30` independently.

---

## Out of scope

Explicitly deferred:

- **Arbitrary two-range comparison** (`--range-a X..Y --range-b Z..W`) — covered by the "Period-over-period only" answer; revisit if a use case appears.
- **N-way overlays** (3+ windows) — BI guidance says 2-3 max for legibility; YAGNI for now.
- **`--last` with week/month units** — calendar ambiguity (month = 30d or actual?). Add when a use case requires it.
- **YoY comparisons** (same week last year) — requires a `--prior-offset` flag; not in scope. Could be a v2.
- **Per-machine breakdown within the overlay** — current design hides the chonkers vs llamabox split. The label info is in the caption text but not in the bars. Adding it would require stacking within each grouped bar (4-color complexity for 2 machines × 2 windows) — defer until requested.
- **Screenshot for the README** — deferred to user, like the trend-graph screenshot.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| `trend_data.py` extraction breaks plot-trend.py | Existing `test_buckets.py` covers `bucket_key`/`auto_bucket`. Add a smoke-test step to the plan: run `plot-trend.py --month 2026-04` before-vs-after the extraction and diff the HTML output. |
| User confuses "bucket-index" view with calendar dates | Bucket labels explicitly show both windows' calendar dates ("Day 1 (Mon 05-04 / Mon 04-27)") — the absolute dates are recoverable visually. |
| `--last 168h` totals drift between runs (sessions accumulate over time) | Document in the script docstring: `--last` is anchored to "now at parse time"; not deterministic across runs. Use `--month` or `--start`/`--end` for stable totals. |
| `plot-compare.py` ends up duplicating plot-trend.py CLI plumbing | The refactor into `trend_data.py` is the prevention. `_month_bounds`, `_date_bounds`, `read_sessions_in_range` move there; both scripts import them. |

---

## Build sequence preview (informs the plan)

The implementation plan should sequence roughly:

1. Extract `trend_data.py` from plot-trend.py — keep behavior identical, regression-diff HTML output
2. Add `parse_last` to trend_data.py with tests
3. Add `prior_window_for` helper to trend_data.py with tests (handles all three modes: month, range, duration)
4. Write `plot-compare.py` minimum skeleton: CLI parsing + bucket math (no chart yet)
5. Add chart rendering — start from `compare-168h-plot.py`'s template, adapt to use auto-bucketing
6. Wire up `--open`, default output path, cross-validation smoke
7. Update README.md, SKILL.md, README Files list
8. Delete the one-off `~/skills-dev/.claude/scripts/compare-168h-plot.py` — superseded by plot-compare.py. **Keep** `compare-168h.py` (text-mode side-by-side report) — that has no replacement in this design; a text-comparison mode is a separate future feature.
9. Test runner already exists (`run-tests.{sh,bat}`) — verify both test files included

Each step gets its own task with clear acceptance criteria in the plan.
