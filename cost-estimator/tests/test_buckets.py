"""Unit smoke for bucket helpers in trend_data.py."""

from __future__ import annotations

import csv
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from trend_data import (  # noqa: E402
    auto_bucket,
    bucket_index,
    bucket_key,
    parse_last,
    inclusive_month_bounds,
    inclusive_date_bounds,
    read_sessions_in_range,
)


def test_day_bucket():
    assert bucket_key(datetime(2026, 4, 12), "day") == "2026-04-12"


def test_month_bucket():
    assert bucket_key(datetime(2026, 4, 12), "month") == "2026-04"


def test_week_bucket_simple():
    # 2026-04-13 is a Monday, ISO 2026-W16
    assert bucket_key(datetime(2026, 4, 13), "week") == "2026-W16"


def test_week_bucket_iso_year_boundary():
    """2024-12-30 (Monday) belongs to ISO 2025-W01.

    ISO week 1 is the week containing the first Thursday of the year.
    2025-01-01 is a Wednesday, so first Thursday is 2025-01-02, and
    week 1 starts Mon 2024-12-30.
    """
    assert bucket_key(datetime(2024, 12, 30), "week") == "2025-W01"


def test_auto_bucket_picker():
    assert auto_bucket(days=7) == "day"
    assert auto_bucket(days=14) == "day"
    assert auto_bucket(days=15) == "week"
    assert auto_bucket(days=90) == "week"
    assert auto_bucket(days=91) == "month"


def test_bucket_by_index_within_window():
    """Two timestamps separated by 36h fall in bucket 0 and bucket 1 at day granularity."""
    window_start = datetime(2026, 5, 4, 9, 30, 0)
    t0 = window_start + timedelta(hours=1)
    t1 = window_start + timedelta(hours=36)
    assert bucket_index(t0, window_start, "day") == 0
    assert bucket_index(t1, window_start, "day") == 1


def test_parse_last_hours():
    assert parse_last("168h") == timedelta(hours=168)


def test_parse_last_days():
    assert parse_last("7d") == timedelta(days=7)


def test_parse_last_rejects_bad_suffix():
    try:
        parse_last("4w")
    except ValueError:
        return
    raise AssertionError("expected ValueError for '4w'")


def test_parse_last_rejects_non_digit():
    try:
        parse_last("abc168h")
    except ValueError:
        return
    raise AssertionError("expected ValueError for 'abc168h'")


def test_parse_last_rejects_zero():
    try:
        parse_last("0d")
    except ValueError:
        return
    raise AssertionError("expected ValueError for '0d'")


def test_inclusive_month_bounds_is_naive_and_end_inclusive():
    """Distinct contract from roots.month_bounds(): naive datetimes, end
    inclusive at 23:59:59.999999 of the last day of the month (not the
    tz-aware, half-open [start, end) that roots.py uses). Fully inclusive
    (not just to-the-second) so sub-second timestamps late on the last
    day aren't dropped by the `<=` comparison in read_sessions_in_range().
    """
    start, end = inclusive_month_bounds("2026-04")
    assert start == datetime(2026, 4, 1)
    assert start.tzinfo is None
    assert end == datetime(2026, 4, 30, 23, 59, 59, 999999)


def test_inclusive_month_bounds_december_rolls_year():
    start, end = inclusive_month_bounds("2026-12")
    assert start == datetime(2026, 12, 1)
    assert end == datetime(2026, 12, 31, 23, 59, 59, 999999)


def test_inclusive_date_bounds_end_is_23_59_59_same_day():
    """Distinct contract from roots.date_bounds(): naive, end bumped to
    23:59:59.999999 of the given end day (not exclusive next-day
    midnight), fully inclusive so sub-second timestamps aren't dropped."""
    start, end = inclusive_date_bounds("2026-04-01", "2026-04-30")
    assert start == datetime(2026, 4, 1)
    assert start.tzinfo is None
    assert end == datetime(2026, 4, 30, 23, 59, 59, 999999)


def test_read_sessions_in_range_includes_subsecond_boundary_timestamp():
    """Regression for the off-by-fractional-second bug: a session whose
    first_timestamp is 23:59:59.500 on the last day of the range must
    still be picked up by read_sessions_in_range() when the range end
    comes from inclusive_date_bounds(). Real Claude Code session JSONLs
    carry millisecond-precision timestamps (e.g. "...T22:14:28.667Z"),
    so this boundary is reachable with real data, not just synthetic."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        csv_path = Path(tmp_dir) / "sessions.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["first_timestamp", "cost_usd"])
            writer.writeheader()
            writer.writerow(
                {
                    "first_timestamp": "2026-04-30T23:59:59.500000",
                    "cost_usd": "1.23",
                }
            )
        range_start, range_end = inclusive_date_bounds("2026-04-01", "2026-04-30")
        rows, skipped = read_sessions_in_range(csv_path, range_start, range_end)
        assert skipped == 0
        assert len(rows) == 1


if __name__ == "__main__":
    test_day_bucket()
    test_month_bucket()
    test_week_bucket_simple()
    test_week_bucket_iso_year_boundary()
    test_auto_bucket_picker()
    test_bucket_by_index_within_window()
    test_parse_last_hours()
    test_parse_last_days()
    test_parse_last_rejects_bad_suffix()
    test_parse_last_rejects_non_digit()
    test_parse_last_rejects_zero()
    test_inclusive_month_bounds_is_naive_and_end_inclusive()
    test_inclusive_month_bounds_december_rolls_year()
    test_inclusive_date_bounds_end_is_23_59_59_same_day()
    test_read_sessions_in_range_includes_subsecond_boundary_timestamp()
    print("OK")
