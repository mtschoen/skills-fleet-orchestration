"""Unit smoke for prior_window_for() in trend_data.py."""

from __future__ import annotations

import sys
from datetime import datetime
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
