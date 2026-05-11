"""Render aggregate Claude Code cost trend across sessions as an HTML chart.

Reads sessions.csv (the artifact written by analyze-month.py), buckets
sessions by their first_timestamp into day/week/month bins, stacks the
per-bucket cost by machine label, and overlays a cumulative-total line
on a right y-axis. Visual idiom matches plot-session.py.

Usage:
    python plot-trend.py
        (--month YYYY-MM | --start YYYY-MM-DD --end YYYY-MM-DD)
        [--bucket {day,week,month}]
        [--csv <path>]
        [--inline-js]
        [--out <path>]
        [--open]
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
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


def pivot_to_datasets(rows: list[dict], granularity: str):
    """Pivot per-row costs into per-(label, bucket) totals + a cumulative
    line.

    Returns (buckets_sorted, per_label_costs, cumulative, per_label_counts):
      - buckets_sorted: list[str], the unique bucket keys present in
        the data, in chronological (lexical) order.
      - per_label_costs: dict[label, list[float]] — each list aligned
        with buckets_sorted, zero-filled where the (label, bucket) had
        no sessions.
      - cumulative: list[float] aligned with buckets_sorted, running
        total across all labels.
      - per_label_counts: dict[label, list[int]] — session counts per
        bucket, used by hover tooltips at render time.
    """
    sums = defaultdict(lambda: defaultdict(float))     # sums[label][bucket]
    counts = defaultdict(lambda: defaultdict(int))     # counts[label][bucket]
    bucket_set = set()
    label_set = set()
    for row in rows:
        key = bucket_key(row["_parsed_timestamp"], granularity)
        label = row["label"]
        sums[label][key] += row["_cost_usd_float"]
        counts[label][key] += 1
        bucket_set.add(key)
        label_set.add(label)

    buckets_sorted = sorted(bucket_set)
    labels_sorted = sorted(label_set)
    per_label_costs = {
        label: [round(sums[label].get(bucket, 0.0), 4) for bucket in buckets_sorted]
        for label in labels_sorted
    }
    per_label_counts = {
        label: [counts[label].get(bucket, 0) for bucket in buckets_sorted]
        for label in labels_sorted
    }

    cumulative = []
    running = 0.0
    for bucket in buckets_sorted:
        for label in labels_sorted:
            running += sums[label].get(bucket, 0.0)
        cumulative.append(round(running, 4))

    return buckets_sorted, per_label_costs, cumulative, per_label_counts
