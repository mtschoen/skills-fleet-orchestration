"""Unit smoke for bucket helpers in trend_data.py."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from trend_data import (  # noqa: E402
    auto_bucket, bucket_index, bucket_key, parse_last,
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
    print("OK")
