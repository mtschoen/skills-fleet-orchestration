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


if __name__ == "__main__":
    test_day_bucket()
    test_month_bucket()
    test_week_bucket_simple()
    test_week_bucket_iso_year_boundary()
    test_auto_bucket_picker()
    print("OK")
