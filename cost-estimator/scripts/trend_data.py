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
            # Drop tzinfo so callers can pass naive boundary datetimes
            # (argparse-derived from "YYYY-MM-DD" strings). The trend
            # chart treats sessions in local wall-clock anyway.
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
