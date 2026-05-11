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

from datetime import datetime


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
