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

## Phase 1: Extract `trend_data.py`

Pure refactor. Move the shared helpers out of `plot-trend.py` into a new importable module so `plot-compare.py` doesn't have to either duplicate them or do the importlib-spec dance. Side benefit: `test_buckets.py` drops its importlib hack.

### Task 1: Extract bucket/range/CSV helpers into `scripts/trend_data.py`

**Files:**
- Create: `cost-estimator/scripts/trend_data.py`
- Modify: `cost-estimator/scripts/plot-trend.py` (remove the 5 extracted functions; add `from trend_data import …`; rename `_month_bounds`→`month_bounds`, `_date_bounds`→`date_bounds` at the two call sites in `main()`)
- Modify: `cost-estimator/scripts/test_buckets.py` (drop importlib hack; `from trend_data import bucket_key, auto_bucket`)

- [x] **Step 1: Create `scripts/trend_data.py` with the 5 extracted functions**

Lift verbatim from `plot-trend.py` (lines 34-103 and 298-323 in the current file). Apply the public-name renames (drop the leading underscore on `month_bounds` and `date_bounds`).

```python
"""Shared bucket math, CSV reading, and range parsing for cost-estimator
trend plotters.

Holds the bits that would literally duplicate between plot-trend.py
(stacked-by-label single-range trend) and plot-compare.py (period-over-
period overlay). Anything that only one plotter needs (label palette,
HTML template, render function) stays in that plotter's own file.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path


def bucket_key(timestamp: datetime, granularity: str) -> str:
    """Return a stable string key for grouping by day, week, or month.

    Keys are designed to sort lexically into chronological order so
    `sorted(bucket_set)` in the pivot step yields the right x-axis
    ordering without parsing.

    - day:   "2026-04-12"
    - week:  "YYYY-Www" using ISO week numbering (year may differ from
             timestamp.year near Jan/Dec boundaries)
    - month: "2026-04"  (locale-immune, lexically sortable; display
             formatting like "Apr 2026" happens at render time)
    """
    if granularity == "day":
        return timestamp.strftime("%Y-%m-%d")
    if granularity == "week":
        iso_year, iso_week, _ = timestamp.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if granularity == "month":
        return timestamp.strftime("%Y-%m")
    raise ValueError(f"unknown granularity: {granularity!r}")


def auto_bucket(days: int) -> str:
    """Pick a bucket granularity from a date-range span."""
    if days <= 14:
        return "day"
    if days <= 90:
        return "week"
    return "month"


def read_sessions_in_range(csv_path: Path, range_start: datetime,
                           range_end: datetime):
    """Read rows of sessions.csv whose first_timestamp falls in
    [range_start, range_end] (inclusive).

    Boundaries should be NAIVE datetimes (no tzinfo). The CSV stores
    tz-aware timestamps; this function strips tzinfo on parse so the
    range comparison works without the caller needing to know.

    Returns (rows, skipped) where:
      - rows: list of dicts with two extra fields per row:
          "_parsed_timestamp" (datetime, naive) and "_cost_usd_float" (float)
      - skipped: count of rows with missing/unparseable first_timestamp
    """
    rows = []
    skipped = 0
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timestamp_string = row.get("first_timestamp") or ""
            if not timestamp_string:
                skipped += 1
                continue
            try:
                timestamp = datetime.fromisoformat(timestamp_string)
            except ValueError:
                skipped += 1
                continue
            if timestamp.tzinfo is not None:
                timestamp = timestamp.replace(tzinfo=None)
            if range_start <= timestamp <= range_end:
                row["_parsed_timestamp"] = timestamp
                row["_cost_usd_float"] = float(row.get("cost_usd") or 0)
                rows.append(row)
    return rows, skipped


def month_bounds(month_string: str) -> tuple[datetime, datetime]:
    """Return (start, inclusive_end) for a YYYY-MM string.

    Inclusive end is one second before the start of the next month so
    that callers passing the pair into read_sessions_in_range() with an
    inclusive comparison match every timestamp in the month.
    """
    year, month = (int(part) for part in month_string.split("-"))
    start = datetime(year, month, 1)
    if month == 12:
        end_exclusive = datetime(year + 1, 1, 1)
    else:
        end_exclusive = datetime(year, month + 1, 1)
    return start, end_exclusive - timedelta(seconds=1)


def date_bounds(start_string: str, end_string: str) -> tuple[datetime, datetime]:
    """Return (start, inclusive_end) for YYYY-MM-DD start + end strings.

    End is bumped to 23:59:59 of the end day so the inclusive comparison
    in read_sessions_in_range() picks up sessions that started late on
    that day.
    """
    start = datetime.fromisoformat(start_string)
    end = datetime.fromisoformat(end_string).replace(hour=23, minute=59, second=59)
    return start, end
```

- [x] **Step 2: Capture pre-edit baseline HTML from `plot-trend.py`**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
python scripts/plot-trend.py --month 2026-04 --out /tmp/trend-before-month.html
python scripts/plot-trend.py --start 2026-04-15 --end 2026-04-21 --out /tmp/trend-before-range.html
```

Both should produce HTML files; note totals from stderr (e.g. `Wrote …`). Sessions.csv must already cover April 2026 for these to work — if not, run `python scripts/analyze-month.py C:/Users/mtsch/.claude/projects --month 2026-04` first.

- [x] **Step 3: Edit `plot-trend.py` — drop the 5 extracted functions, add import, rename call sites**

In `scripts/plot-trend.py`:

1. **Drop** the function definitions for `bucket_key`, `auto_bucket`, `read_sessions_in_range`, `_month_bounds`, `_date_bounds` (lines 34-63, 66-103, 298-323 in the pre-edit file).
2. **Add** import after the existing `from chart_runtime import …` line:

```python
from trend_data import (  # noqa: E402
    bucket_key, auto_bucket, read_sessions_in_range,
    month_bounds, date_bounds,
)
```

3. **Rename call sites** in `main()`:
   - `_month_bounds(arguments.month)` → `month_bounds(arguments.month)`
   - `_date_bounds(arguments.start, arguments.end)` → `date_bounds(arguments.start, arguments.end)`

Imports no longer needed in `plot-trend.py`: `csv` and `timedelta` may still be needed inside the empty-range probe; verify by running the script. If `csv` is unused at module scope, drop the `import csv` line.

- [x] **Step 4: Update `scripts/test_buckets.py` to import directly**

```python
"""Unit smoke for bucket helpers in trend_data.py."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from trend_data import bucket_key, auto_bucket  # noqa: E402


def test_day_bucket():
    assert bucket_key(datetime(2026, 4, 12), "day") == "2026-04-12"


def test_month_bucket():
    assert bucket_key(datetime(2026, 4, 12), "month") == "2026-04"


def test_week_bucket_simple():
    # 2026-04-13 is a Monday, ISO 2026-W16
    assert bucket_key(datetime(2026, 4, 13), "week") == "2026-W16"


def test_week_bucket_iso_year_boundary():
    """2024-12-30 (Monday) belongs to ISO 2025-W01."""
    assert bucket_key(datetime(2024, 12, 30), "week") == "2025-W01"


def test_auto_bucket_picker():
    assert auto_bucket(days=7) == "day"
    assert auto_bucket(days=14) == "day"
    assert auto_bucket(days=15) == "week"
    assert auto_bucket(days=90) == "week"
    assert auto_bucket(days=91) == "month"


if __name__ == "__main__":
    test_day_bucket()
    test_month_bucket()
    test_week_bucket_simple()
    test_week_bucket_iso_year_boundary()
    test_auto_bucket_picker()
    print("OK")
```

- [x] **Step 5: Capture post-edit HTML + diff**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
python scripts/plot-trend.py --month 2026-04 --out /tmp/trend-after-month.html
python scripts/plot-trend.py --start 2026-04-15 --end 2026-04-21 --out /tmp/trend-after-range.html
diff /tmp/trend-before-month.html /tmp/trend-after-month.html
diff /tmp/trend-before-range.html /tmp/trend-after-range.html
```

Expected: both diffs empty (no output). If either has output, the refactor isn't byte-identical — investigate before committing.

- [x] **Step 6: Run tests**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
bash scripts/run-tests.sh
```

Expected: prints `OK` twice (one per test file), then `All tests passed.`

- [x] **Step 7: Commit**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
git add scripts/trend_data.py scripts/plot-trend.py scripts/test_buckets.py
git commit -m "trend_data: extract bucket/range/csv helpers from plot-trend

Pure refactor in preparation for plot-compare.py. Moves bucket_key,
auto_bucket, read_sessions_in_range, _month_bounds (renamed to
month_bounds), and _date_bounds (renamed to date_bounds) into a new
scripts/trend_data.py module so plot-trend.py and the upcoming
plot-compare.py share the same logic without one importing the other
via importlib-spec hacks (plot-trend.py has a hyphen and can't be
imported normally). test_buckets.py loses its importlib hack as a
side benefit.

Regression-verified byte-identical HTML output from plot-trend.py for
both --month and --start/--end invocations.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2: New helpers in `trend_data.py`

TDD: failing test → minimal implementation → green → commit. Two helpers: `parse_last` (CLI shorthand for "last Nh/Nd") and `prior_window_for` (compute the same-length prior window for any of the three CLI modes).

### Task 2: Add `parse_last("168h"|"7d") → timedelta`

**Files:**
- Modify: `cost-estimator/scripts/trend_data.py` (add `parse_last` after `auto_bucket`)
- Modify: `cost-estimator/scripts/test_buckets.py` (add 5 tests)

- [ ] **Step 1: Add failing tests to `test_buckets.py`**

Append after `test_auto_bucket_picker` (and before the `if __name__ == "__main__":` block):

```python
def test_parse_last_hours():
    from trend_data import parse_last
    from datetime import timedelta
    assert parse_last("168h") == timedelta(hours=168)


def test_parse_last_days():
    from trend_data import parse_last
    from datetime import timedelta
    assert parse_last("7d") == timedelta(days=7)


def test_parse_last_rejects_bad_suffix():
    from trend_data import parse_last
    try:
        parse_last("4w")
    except ValueError:
        return
    raise AssertionError("expected ValueError for '4w'")


def test_parse_last_rejects_non_digit():
    from trend_data import parse_last
    try:
        parse_last("abc168h")
    except ValueError:
        return
    raise AssertionError("expected ValueError for 'abc168h'")


def test_parse_last_rejects_zero():
    from trend_data import parse_last
    try:
        parse_last("0d")
    except ValueError:
        return
    raise AssertionError("expected ValueError for '0d'")
```

Update the `if __name__ == "__main__":` block to call them:

```python
if __name__ == "__main__":
    test_day_bucket()
    test_month_bucket()
    test_week_bucket_simple()
    test_week_bucket_iso_year_boundary()
    test_auto_bucket_picker()
    test_parse_last_hours()
    test_parse_last_days()
    test_parse_last_rejects_bad_suffix()
    test_parse_last_rejects_non_digit()
    test_parse_last_rejects_zero()
    print("OK")
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
python scripts/test_buckets.py
```

Expected: `ImportError: cannot import name 'parse_last' from 'trend_data'` (or `AttributeError` depending on import shape).

- [ ] **Step 3: Implement `parse_last` in `trend_data.py`**

Append after `auto_bucket`:

```python
def parse_last(value: str) -> timedelta:
    """Parse '168h' or '7d' shorthand into a timedelta.

    Accepts only hours and days for v1 (weeks / months deferred — calendar
    ambiguity for 'mo'). Raises ValueError on malformed input.
    """
    if not value or len(value) < 2:
        raise ValueError(f"--last must be <digits>(h|d), got {value!r}")
    quantity_part, suffix = value[:-1], value[-1]
    if not quantity_part.isdigit():
        raise ValueError(f"--last must be <digits>(h|d), got {value!r}")
    quantity = int(quantity_part)
    if quantity <= 0:
        raise ValueError(f"--last must be positive, got {value!r}")
    if suffix == "h":
        return timedelta(hours=quantity)
    if suffix == "d":
        return timedelta(days=quantity)
    raise ValueError(f"--last suffix must be 'h' or 'd', got {value!r}")
```

- [ ] **Step 4: Run tests — expect green**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
bash scripts/run-tests.sh
```

Expected: `OK` from both test files, `All tests passed.`

- [ ] **Step 5: Commit**

```bash
git add scripts/trend_data.py scripts/test_buckets.py
git commit -m "trend_data: add parse_last('168h'|'7d') -> timedelta

CLI shorthand parser for plot-compare.py's --last flag. Accepts only
hours and days for v1; weeks/months deferred per YAGNI (calendar
ambiguity for 'mo'). Rejects empty input, non-digit prefixes, zero or
negative quantities, and unknown suffixes via ValueError.

5 tests cover happy paths (hours, days), bad suffix, non-digit prefix,
and zero rejection.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Add `prior_window_for(start, end, *, mode)` helper

**Files:**
- Modify: `cost-estimator/scripts/trend_data.py` (add `prior_window_for` after `date_bounds`)
- Create: `cost-estimator/scripts/test_compare.py` (new test file)
- Modify: `cost-estimator/scripts/run-tests.sh` (add `python test_compare.py`)
- Modify: `cost-estimator/scripts/run-tests.bat` (add `python test_compare.py` + errorlevel check)

- [ ] **Step 1: Write `scripts/test_compare.py` with failing tests**

```python
"""Unit smoke for prior_window_for() in trend_data.py."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from trend_data import prior_window_for  # noqa: E402


def test_prior_window_for_month():
    """April -> March, end-inclusive at 23:59:59 of last day."""
    current_start = datetime(2026, 4, 1)
    current_end = datetime(2026, 4, 30, 23, 59, 59)
    prior_start, prior_end = prior_window_for(
        current_start, current_end, mode="month",
    )
    assert prior_start == datetime(2026, 3, 1)
    assert prior_end == datetime(2026, 3, 31, 23, 59, 59)


def test_prior_window_for_month_year_rollover():
    """January 2026 -> December 2025."""
    current_start = datetime(2026, 1, 1)
    current_end = datetime(2026, 1, 31, 23, 59, 59)
    prior_start, prior_end = prior_window_for(
        current_start, current_end, mode="month",
    )
    assert prior_start == datetime(2025, 12, 1)
    assert prior_end == datetime(2025, 12, 31, 23, 59, 59)


def test_prior_window_for_arbitrary_range():
    """Apr 15-21 (7-day inclusive) -> Apr 8-14."""
    current_start = datetime(2026, 4, 15)
    current_end = datetime(2026, 4, 21, 23, 59, 59)
    prior_start, prior_end = prior_window_for(
        current_start, current_end, mode="range",
    )
    assert prior_start == datetime(2026, 4, 8)
    assert prior_end == datetime(2026, 4, 14, 23, 59, 59)


def test_prior_window_for_duration_half_open():
    """--last 168h: prior_end exactly equals current_start (half-open)."""
    current_start = datetime(2026, 5, 4, 9, 30, 0)
    current_end = datetime(2026, 5, 11, 9, 30, 0)
    prior_start, prior_end = prior_window_for(
        current_start, current_end, mode="duration",
    )
    assert prior_start == datetime(2026, 4, 27, 9, 30, 0)
    assert prior_end == datetime(2026, 5, 4, 9, 30, 0)


def test_prior_window_for_rejects_unknown_mode():
    try:
        prior_window_for(datetime(2026, 1, 1), datetime(2026, 1, 2), mode="bogus")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unknown mode")


if __name__ == "__main__":
    test_prior_window_for_month()
    test_prior_window_for_month_year_rollover()
    test_prior_window_for_arbitrary_range()
    test_prior_window_for_duration_half_open()
    test_prior_window_for_rejects_unknown_mode()
    print("OK")
```

- [ ] **Step 2: Add `test_compare.py` to test runner scripts**

`scripts/run-tests.sh`:

```bash
#!/usr/bin/env bash
# Run all unit tests in cost-estimator/scripts. Exits non-zero on first failure.
set -euo pipefail
cd "$(dirname "$0")"
python test_buckets.py
python test_resolve_roots.py
python test_compare.py
echo "All tests passed."
```

`scripts/run-tests.bat` (remember CRLF after writing):

```batch
@echo off
rem Run all unit tests in cost-estimator/scripts. Exits non-zero on first failure.
setlocal
cd /d "%~dp0"
python test_buckets.py
if errorlevel 1 exit /b %errorlevel%
python test_resolve_roots.py
if errorlevel 1 exit /b %errorlevel%
python test_compare.py
if errorlevel 1 exit /b %errorlevel%
echo All tests passed.
```

After writing `.bat`, convert to CRLF:
```bash
sed -i 's/$/\r/' C:/Users/mtsch/skills-dev/cost-estimator/scripts/run-tests.bat
```

- [ ] **Step 3: Run tests — expect failure**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
python scripts/test_compare.py
```

Expected: `ImportError: cannot import name 'prior_window_for' from 'trend_data'`.

- [ ] **Step 4: Implement `prior_window_for` in `trend_data.py`**

Append after `date_bounds`:

```python
def prior_window_for(
    current_start: datetime, current_end: datetime, *, mode: str,
) -> tuple[datetime, datetime]:
    """Return (prior_start, prior_end) for the same-length window
    immediately before [current_start, current_end].

    Three modes, distinguished by their end-inclusivity convention:

    - "month":    prior is the calendar month before current_start
                  (handles Dec -> Jan year rollover via month_bounds).
    - "range":    inclusive end (--start/--end). prior duration =
                  current_end - current_start; prior_end is 1 second
                  before current_start.
    - "duration": half-open end (--last). prior duration is the same;
                  prior_end equals current_start exactly.
    """
    if mode == "month":
        # current_start is always YYYY-MM-01 00:00 in this mode.
        if current_start.month == 1:
            prior_month_string = f"{current_start.year - 1:04d}-12"
        else:
            prior_month_string = f"{current_start.year:04d}-{current_start.month - 1:02d}"
        return month_bounds(prior_month_string)
    if mode == "range":
        duration = current_end - current_start
        prior_start = current_start - duration - timedelta(seconds=1)
        prior_end = current_start - timedelta(seconds=1)
        return prior_start, prior_end
    if mode == "duration":
        duration = current_end - current_start
        prior_start = current_start - duration
        prior_end = current_start
        return prior_start, prior_end
    raise ValueError(f"unknown mode {mode!r} (expected 'month', 'range', 'duration')")
```

- [ ] **Step 5: Run tests — expect green**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
bash scripts/run-tests.sh
```

Expected: `OK` from all three test files, then `All tests passed.`

- [ ] **Step 6: Commit**

```bash
git add scripts/trend_data.py scripts/test_compare.py scripts/run-tests.sh scripts/run-tests.bat
git commit -m "trend_data: add prior_window_for(start, end, *, mode) helper

Converges all three plot-compare CLI modes (month / range / duration) to
a single (prior_start, prior_end) tuple. The 'range' vs 'duration'
distinction is end-inclusivity: --start/--end is inclusive (prior_end is
1 second before current_start), while --last is half-open (prior_end
equals current_start). 'month' mode delegates to month_bounds() so the
Dec -> Jan year rollover stays in one place.

5 tests cover: month happy path, year rollover, arbitrary range,
duration half-open, unknown-mode rejection. run-tests.{sh,bat} picks
up the new test_compare.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3: `plot-compare.py`

Build the script in three commits: skeleton (CLI + window math), then chart rendering, then smoke + cross-validation.

### Task 4: `plot-compare.py` CLI skeleton — parse args, compute windows, print

**Files:**
- Create: `cost-estimator/scripts/plot-compare.py`

- [ ] **Step 1: Write `scripts/plot-compare.py` skeleton**

```python
"""Render any window vs the same-length prior window as an overlaid
Chart.js HTML chart (grouped bars per bucket + twin cumulative lines).

Reads sessions.csv (the artifact written by analyze-month.py), filters
each row into the current window or the prior window by its
first_timestamp, buckets sessions by their position WITHIN their window
(bucket-index, not calendar date), and renders the overlay.

Usage:
    python plot-compare.py
        (--month YYYY-MM | --start YYYY-MM-DD --end YYYY-MM-DD | --last <Nh|Nd>)
        [--bucket {day,week,month}]
        [--csv <path>]
        [--inline-js]
        [--out <path>]
        [--open]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from trend_data import (  # noqa: E402
    auto_bucket, bucket_index, date_bounds, month_bounds, num_buckets,
    parse_last, prior_window_for, read_sessions_in_range,
)

DEFAULT_CSV_PATH = Path(__file__).resolve().parent.parent / "reports" / "sessions.csv"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "reports"


def _resolve_current_window(arguments, parser):
    """Return (current_start, current_end, mode, range_label, range_filename, span_days).

    Centralizes the three-mode dispatch so main() reads cleanly.
    """
    if arguments.month:
        try:
            current_start, current_end = month_bounds(arguments.month)
        except ValueError:
            parser.error(f"--month must be YYYY-MM, got {arguments.month!r}")
        return (current_start, current_end, "month",
                arguments.month, arguments.month,
                (current_end - current_start).days + 1)
    if arguments.start:
        if not arguments.end:
            parser.error("--start requires --end")
        current_start, current_end = date_bounds(arguments.start, arguments.end)
        return (current_start, current_end, "range",
                f"{arguments.start} → {arguments.end}",
                f"{arguments.start}_{arguments.end}",
                (current_end - current_start).days + 1)
    if arguments.last:
        try:
            duration = parse_last(arguments.last)
        except ValueError as exc:
            parser.error(str(exc))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        current_start = now - duration
        current_end = now
        return (current_start, current_end, "duration",
                f"last {arguments.last}", f"last-{arguments.last}",
                max(1, duration.days or (duration.total_seconds() // 86400) + 1))
    parser.error("one of --month, --start/--end, --last is required")


def main():
    parser = argparse.ArgumentParser(
        description="Render current vs prior same-length window as an overlay chart."
    )
    range_group = parser.add_mutually_exclusive_group()
    range_group.add_argument("--month", help="YYYY-MM")
    range_group.add_argument("--start", help="YYYY-MM-DD start (requires --end)")
    range_group.add_argument("--last", help="<digits>(h|d), e.g. 168h or 7d")
    parser.add_argument("--end", help="YYYY-MM-DD end (paired with --start)")
    parser.add_argument("--bucket", choices=("day", "week", "month"), default=None)
    parser.add_argument("--csv", default=str(DEFAULT_CSV_PATH))
    parser.add_argument("--inline-js", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--open", dest="open_browser", action="store_true")
    arguments = parser.parse_args()

    if arguments.month and arguments.end:
        parser.error("--end requires --start, not --month")
    if arguments.last and arguments.end:
        parser.error("--end requires --start, not --last")

    (current_start, current_end, mode,
     range_label, range_filename, span_days) = _resolve_current_window(arguments, parser)
    prior_start, prior_end = prior_window_for(current_start, current_end, mode=mode)
    granularity = arguments.bucket or auto_bucket(int(span_days))

    print(f"Current window: {current_start.isoformat()} .. {current_end.isoformat()}",
          file=sys.stderr)
    print(f"Prior window:   {prior_start.isoformat()} .. {prior_end.isoformat()}",
          file=sys.stderr)
    print(f"Bucket: {granularity} (span={int(span_days)} days, mode={mode})",
          file=sys.stderr)

    csv_path = Path(arguments.csv)
    if not csv_path.is_file():
        sys.exit(f"error: sessions.csv not found at {csv_path}. "
                 f"Run analyze-month.py first, or pass --csv <path>.")

    current_rows, _ = read_sessions_in_range(csv_path, current_start, current_end)
    prior_rows, _ = read_sessions_in_range(csv_path, prior_start, prior_end)
    print(f"Current rows: {len(current_rows)}  Prior rows: {len(prior_rows)}",
          file=sys.stderr)

    if not current_rows and not prior_rows:
        sys.exit("error: no sessions in either window. Check --csv path and range.")

    # Rendering follows in Task 5.
    print("(skeleton — chart rendering lands in Task 5)", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-test CLI surface**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
python scripts/plot-compare.py --month 2026-04 2>&1 | tail -5
python scripts/plot-compare.py --start 2026-04-15 --end 2026-04-21 2>&1 | tail -5
python scripts/plot-compare.py --last 168h 2>&1 | tail -5
echo "---error paths---"
python scripts/plot-compare.py --month banana 2>&1 | tail -1
python scripts/plot-compare.py --month 2026-04 --end 2026-04-15 2>&1 | tail -1
python scripts/plot-compare.py --last 4w 2>&1 | tail -1
python scripts/plot-compare.py 2>&1 | tail -1
```

Expected:
- The three happy paths print current + prior window timestamps and the row counts. `--month 2026-04` should show current `2026-04-01..2026-04-30 23:59:59` and prior `2026-03-01..2026-03-31 23:59:59`. `--start 2026-04-15 --end 2026-04-21` should show prior `2026-04-08..2026-04-14 23:59:59`.
- `--month banana` → `error: --month must be YYYY-MM, got 'banana'`
- `--month 2026-04 --end 2026-04-15` → `error: --end requires --start, not --month`
- `--last 4w` → `error: --last suffix must be 'h' or 'd', got '4w'`
- bare `--no args--` → `error: one of --month, --start/--end, --last is required`

- [ ] **Step 3: Commit**

```bash
git add scripts/plot-compare.py
git commit -m "plot-compare: CLI skeleton — parse args, compute windows, print

Three mutually-exclusive range flags (--month / --start+--end / --last).
Mirrors plot-trend.py's CLI conventions and inherits its hardening from
the trend-graph close-out (friendly --month errors via parser.error,
explicit --end-vs-other-flag rejection). The prior window is auto-
derived via prior_window_for() based on the mode of the current window.

Skeleton only — prints both windows + row counts and exits. Chart
rendering lands in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Bucketing + chart rendering

**Files:**
- Modify: `cost-estimator/scripts/trend_data.py` (add `bucket_index` and `num_buckets` pure helpers — kept here so test_buckets.py can import them without the importlib hack)
- Modify: `cost-estimator/scripts/test_buckets.py` (add `test_bucket_by_index_within_window`)
- Modify: `cost-estimator/scripts/plot-compare.py` (add row-aggregation helpers + HTML template + render_html; wire into main)

- [ ] **Step 1a: Add `bucket_index` + `num_buckets` to `trend_data.py`**

Append after `prior_window_for`:

```python
def bucket_index(timestamp: datetime, window_start: datetime,
                 granularity: str) -> int:
    """Return 0-based bucket index for a timestamp within its window.

    Distinct from `bucket_key`: bucket-index makes paired bars in an
    overlay chart apples-to-apples wall-clock-relative slices (Day 1
    = first 24h after window_start in BOTH windows), while bucket_key
    is calendar-aligned (good for single-window stacking, wrong for
    cross-window comparison).
    """
    delta = timestamp - window_start
    if granularity == "day":
        return delta.days
    if granularity == "week":
        return delta.days // 7
    if granularity == "month":
        # Approximate: chunks of ~30 days. Calendar months don't align
        # with arbitrary window starts, so use 30-day chunks here for
        # symmetry with day/week.
        return delta.days // 30
    raise ValueError(f"unknown granularity: {granularity!r}")


def num_buckets(span_days: int, granularity: str) -> int:
    """Number of buckets covering a span at the given granularity."""
    if granularity == "day":
        return max(1, span_days)
    if granularity == "week":
        return max(1, (span_days + 6) // 7)
    if granularity == "month":
        return max(1, (span_days + 29) // 30)
    raise ValueError(f"unknown granularity: {granularity!r}")
```

- [ ] **Step 1b: Add `test_bucket_by_index_within_window` to `test_buckets.py`**

Append after `test_auto_bucket_picker` (and before the `test_parse_last_*` tests added in Task 2):

```python
def test_bucket_by_index_within_window():
    """Two timestamps separated by 36h fall in bucket 0 and bucket 1 at day granularity."""
    from trend_data import bucket_index
    from datetime import timedelta
    window_start = datetime(2026, 5, 4, 9, 30, 0)
    t0 = window_start + timedelta(hours=1)
    t1 = window_start + timedelta(hours=36)
    assert bucket_index(t0, window_start, "day") == 0
    assert bucket_index(t1, window_start, "day") == 1
```

Add `test_bucket_by_index_within_window()` to the `if __name__ == "__main__":` block before the `test_parse_last_*` calls.

- [ ] **Step 1c: Add row-aggregation helpers to `plot-compare.py`**

Below the `_resolve_current_window` helper in `plot-compare.py`:

```python
def aggregate_per_bucket(rows, window_start, granularity, total_buckets):
    """Return list[float] of length total_buckets with per-bucket cost."""
    per_bucket = [0.0] * total_buckets
    for row in rows:
        index = bucket_index(row["_parsed_timestamp"], window_start, granularity)
        if 0 <= index < total_buckets:
            per_bucket[index] += row["_cost_usd_float"]
    return [round(value, 2) for value in per_bucket]


def cumulative(per_bucket):
    out = []
    running = 0.0
    for value in per_bucket:
        running += value
        out.append(round(running, 2))
    return out


def bucket_labels(current_start, prior_start, granularity, total_buckets):
    """Build x-axis labels showing both windows' calendar dates per bucket."""
    if granularity == "day":
        unit, fmt = "Day", "%a %m-%d"
        step_days = 1
    elif granularity == "week":
        unit, fmt = "Week", "%m-%d"
        step_days = 7
    else:
        unit, fmt = "Month", "%Y-%m-%d"
        step_days = 30
    labels = []
    from datetime import timedelta
    for index in range(total_buckets):
        current_anchor = current_start + timedelta(days=index * step_days)
        prior_anchor = prior_start + timedelta(days=index * step_days)
        labels.append(
            f"{unit} {index + 1} ({current_anchor.strftime(fmt)} / "
            f"{prior_anchor.strftime(fmt)})"
        )
    return labels
```

- [ ] **Step 2: Add `chart_runtime` import + HTML_TEMPLATE + render_html**

Add to imports near the top:

```python
import json
import webbrowser
from chart_runtime import chartjs_script_tags  # noqa: E402
```

Add `HTML_TEMPLATE` and `render_html` near the other helpers (above `main`):

```python
HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cost compare — {range_label}</title>
{chartjs_script_tag}
<style>
  html, body {{ height: 100%; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 12px; color: #222; }}
  h1 {{ margin: 0 0 4px 0; font-size: 18px; }}
  .sub {{ font-size: 12px; color: #555; margin-bottom: 4px; }}
  .meta {{ font-family: ui-monospace, "Cascadia Mono", Menlo, monospace;
          font-size: 12px; color: #555; margin-bottom: 14px; }}
  .meta span {{ display: inline-block; margin-right: 18px; }}
  .chart-wrap {{ position: relative; width: 100%; height: 72vh; min-height: 460px; }}
  canvas {{ width: 100% !important; height: 100% !important; }}
  .footnote {{ font-size: 11px; color: #888; margin-top: 12px; }}
</style>
</head>
<body>
<h1>Cost comparison — current vs prior</h1>
<div class="sub">Range: {range_label}. Bars and lines below use bucket-index (Day/Week/Month N), so paired columns represent the same wall-clock-relative slice in each window.</div>
<div class="meta">
  <span>current: {current_start} → {current_end} (${current_total:,.2f} / {current_sessions} sessions)</span>
  <span>prior:   {prior_start} → {prior_end} (${prior_total:,.2f} / {prior_sessions} sessions)</span>
</div>
<div class="chart-wrap"><canvas id="chart"></canvas></div>
<div class="footnote">
  Bars: per-bucket cost (left y-axis). Lines: cumulative cost (right y-axis).
</div>
<script>
const LABELS = {labels_json};
const CURRENT_PER_BUCKET = {current_per_bucket_json};
const CURRENT_CUMULATIVE = {current_cumulative_json};
const PRIOR_PER_BUCKET = {prior_per_bucket_json};
const PRIOR_CUMULATIVE = {prior_cumulative_json};

new Chart(document.getElementById("chart"), {{
  data: {{
    labels: LABELS,
    datasets: [
      {{ type: "bar", label: "Current — per bucket", data: CURRENT_PER_BUCKET,
         backgroundColor: "rgba(54, 162, 235, 0.85)",
         borderColor: "rgba(20, 95, 145, 1)", borderWidth: 1,
         yAxisID: "y", order: 2 }},
      {{ type: "bar", label: "Prior — per bucket", data: PRIOR_PER_BUCKET,
         backgroundColor: "rgba(150, 150, 150, 0.75)",
         borderColor: "rgba(80, 80, 80, 1)", borderWidth: 1,
         yAxisID: "y", order: 2 }},
      {{ type: "line", label: "Current — cumulative", data: CURRENT_CUMULATIVE,
         borderColor: "rgba(20, 95, 145, 1)", backgroundColor: "rgba(0,0,0,0)",
         borderWidth: 2, tension: 0.15, pointRadius: 3,
         yAxisID: "y1", order: 1 }},
      {{ type: "line", label: "Prior — cumulative", data: PRIOR_CUMULATIVE,
         borderColor: "rgba(80, 80, 80, 1)", backgroundColor: "rgba(0,0,0,0)",
         borderWidth: 2, borderDash: [6, 4], tension: 0.15, pointRadius: 3,
         yAxisID: "y1", order: 1 }},
    ],
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    interaction: {{ mode: "index", intersect: false }},
    scales: {{
      x: {{ stacked: false, type: "category" }},
      y:  {{ beginAtZero: true, position: "left",
            title: {{ display: true, text: "Per-bucket cost ($)" }} }},
      y1: {{ beginAtZero: true, position: "right",
            grid: {{ drawOnChartArea: false }},
            title: {{ display: true, text: "Cumulative cost ($)" }} }},
    }},
    plugins: {{
      tooltip: {{
        callbacks: {{
          label: (item) => `${{item.dataset.label}}: $${{item.parsed.y.toFixed(2)}}`,
        }},
      }},
    }},
  }},
}});
</script>
</body>
</html>
"""


def render_html(*, range_label, current_start, current_end,
                prior_start, prior_end, current_total, prior_total,
                current_sessions, prior_sessions,
                labels, current_per_bucket, current_cumulative_data,
                prior_per_bucket, prior_cumulative_data, inline):
    chartjs_script_tag, _ = chartjs_script_tags(inline=inline,
                                                want_time_adapter=False)
    return HTML_TEMPLATE.format(
        chartjs_script_tag=chartjs_script_tag,
        range_label=range_label,
        current_start=current_start.isoformat(),
        current_end=current_end.isoformat(),
        prior_start=prior_start.isoformat(),
        prior_end=prior_end.isoformat(),
        current_total=current_total,
        prior_total=prior_total,
        current_sessions=current_sessions,
        prior_sessions=prior_sessions,
        labels_json=json.dumps(labels).replace("</", "<\\/"),
        current_per_bucket_json=json.dumps(current_per_bucket).replace("</", "<\\/"),
        current_cumulative_json=json.dumps(current_cumulative_data).replace("</", "<\\/"),
        prior_per_bucket_json=json.dumps(prior_per_bucket).replace("</", "<\\/"),
        prior_cumulative_json=json.dumps(prior_cumulative_data).replace("</", "<\\/"),
    )
```

- [ ] **Step 3: Wire rendering into `main()`**

Replace the `# Rendering follows in Task 5.` placeholder and the `print("(skeleton ...")` line with:

```python
total_buckets = num_buckets(int(span_days), granularity)
current_per_bucket = aggregate_per_bucket(current_rows, current_start, granularity, total_buckets)
prior_per_bucket = aggregate_per_bucket(prior_rows, prior_start, granularity, total_buckets)
current_cumulative_data = cumulative(current_per_bucket)
prior_cumulative_data = cumulative(prior_per_bucket)
labels = bucket_labels(current_start, prior_start, granularity, total_buckets)

html_text = render_html(
    range_label=range_label,
    current_start=current_start, current_end=current_end,
    prior_start=prior_start, prior_end=prior_end,
    current_total=round(sum(current_per_bucket), 2),
    prior_total=round(sum(prior_per_bucket), 2),
    current_sessions=len(current_rows),
    prior_sessions=len(prior_rows),
    labels=labels,
    current_per_bucket=current_per_bucket,
    current_cumulative_data=current_cumulative_data,
    prior_per_bucket=prior_per_bucket,
    prior_cumulative_data=prior_cumulative_data,
    inline=arguments.inline_js,
)

if arguments.out:
    output_path = Path(arguments.out)
else:
    output_path = DEFAULT_OUT_DIR / f"compare-{range_filename}.html"

output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_text(html_text, encoding="utf-8")
print(f"Wrote {output_path}", file=sys.stderr)

if arguments.open_browser:
    webbrowser.open(output_path.resolve().as_uri())
```

- [ ] **Step 4: End-to-end smoke**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
python scripts/plot-compare.py --month 2026-04 --out /tmp/compare-april.html
grep -c "Cost comparison" /tmp/compare-april.html        # expect 1
grep -c "Current — per bucket" /tmp/compare-april.html   # expect 1 in template
grep -o 'CURRENT_PER_BUCKET = \[[^]]*\]' /tmp/compare-april.html | head -1
```

Expected: HTML written, contains the template + the embedded dataset arrays. Bucket count should be ~4 (April is 30 days, auto-bucket→week, so 5 weekly bars).

```bash
python scripts/plot-compare.py --last 168h --out /tmp/compare-week.html
```

Expected: 7 daily bars (--last 168h = 7d, span_days=7, auto-bucket→day).

- [ ] **Step 5: Commit**

```bash
git add scripts/plot-compare.py
git commit -m "plot-compare: chart rendering — grouped bars + twin cumulative lines

Adds bucket-index aggregation (bucket_index/num_buckets/
aggregate_per_bucket/cumulative/bucket_labels), the embedded HTML
template + Chart.js config, and the render_html function. main() wires
the data flow end-to-end and writes to reports/compare-<range>.html by
default. Smoke-verified against --month 2026-04 (weekly bars) and
--last 168h (daily bars).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Cross-validation smoke

**Files:** no edits — verification only.

- [ ] **Step 1: Run the canonical smoke from the spec**

```bash
cd C:/Users/mtsch/skills-dev/cost-estimator
# Make sure CSV covers both April + March 2026 (regenerate if needed)
python scripts/analyze-month.py C:/Users/mtsch/.claude/projects --label chonkers --start 2026-03-01 --end 2026-04-30 2>&1 | tail -3
# Compare and capture totals
python scripts/plot-compare.py --month 2026-04 --out /tmp/compare-final.html
grep -o 'current_total":[^,]*\|prior_total":[^,]*' /tmp/compare-final.html
# Cross-check April total against summarize.py
python scripts/summarize.py --csv reports/sessions.csv 2>&1 | grep -i 'TOTAL'
```

Expected: April total reported in HTML caption matches summarize.py's TOTAL for the same data. (Exact dollar number will depend on machine state at run time — agreement to within $0.01 is the assertion.)

- [ ] **Step 2: Run `--open` end-to-end**

```bash
python scripts/plot-compare.py --month 2026-04 --open
```

Expected: HTML file opens in the default browser, shows weekly bars + cumulative lines for April vs March.

- [ ] **Step 3: Run all unit tests one more time**

```bash
bash scripts/run-tests.sh
```

Expected: all three test files print `OK`, then `All tests passed.`

- [ ] **Step 4: No commit** — verification only; if anything failed, fix in a follow-up task before proceeding to Phase 4.

---

## Phase 4: Docs + cleanup

### Task 7: Update SKILL.md + README.md

**Files:**
- Modify: `cost-estimator/SKILL.md` (add new step 7 after the plot-trend step; update Files list)
- Modify: `cost-estimator/README.md` (add "## Comparing two windows" section after "## Trend across sessions"; add `plot-compare.py` and `trend_data.py` to Files list)

- [ ] **Step 1: Add step 7 to SKILL.md "Steps" section**

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

- [ ] **Step 2: Add `plot-compare.py` + `trend_data.py` to SKILL.md Files list**

In `cost-estimator/SKILL.md` "Files in this skill" section, after `scripts/plot-trend.py`:

```markdown
- `scripts/plot-compare.py` — period-over-period overlay chart.
  Renders any window vs the same-length prior window (--month /
  --start+--end / --last). Imports bucket helpers from `trend_data.py`.
- `scripts/trend_data.py` — shared bucket math, CSV reader, and range
  parsers. Imported by plot-trend.py and plot-compare.py so the same
  bucketing logic stays in one place.
```

- [ ] **Step 3: Add "## Comparing two windows" section to README.md**

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

- [ ] **Step 4: Add `plot-compare.py` + `trend_data.py` to README Files list**

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

- [ ] **Step 5: Commit**

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
