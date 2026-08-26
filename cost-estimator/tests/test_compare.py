"""Unit smoke for prior_window_for() in trend_data.py."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from trend_data import inclusive_date_bounds, prior_window_for  # noqa: E402


def test_prior_window_for_month():
    """April -> March, end-inclusive at 23:59:59.999999 of last day.

    Mode "month" delegates to inclusive_month_bounds(), so it inherits
    that function's fully-inclusive (not just to-the-second) end.
    """
    current_start = datetime(2026, 4, 1)
    current_end = datetime(2026, 4, 30, 23, 59, 59, 999999)
    prior_start, prior_end = prior_window_for(
        current_start,
        current_end,
        mode="month",
    )
    assert prior_start == datetime(2026, 3, 1)
    assert prior_end == datetime(2026, 3, 31, 23, 59, 59, 999999)


def test_prior_window_for_month_year_rollover():
    """January 2026 -> December 2025."""
    current_start = datetime(2026, 1, 1)
    current_end = datetime(2026, 1, 31, 23, 59, 59, 999999)
    prior_start, prior_end = prior_window_for(
        current_start,
        current_end,
        mode="month",
    )
    assert prior_start == datetime(2025, 12, 1)
    assert prior_end == datetime(2025, 12, 31, 23, 59, 59, 999999)


def test_prior_window_for_arbitrary_range():
    """Apr 15-21 (7-day inclusive) -> Apr 8-14.

    prior_end sits 1 microsecond before current_start, matching the
    microsecond-inclusive convention inclusive_date_bounds() /
    inclusive_month_bounds() use for the current window's own end --
    not the old to-the-second convention, which left a 1-second gap.
    """
    current_start = datetime(2026, 4, 15)
    current_end = datetime(2026, 4, 21, 23, 59, 59, 999999)
    prior_start, prior_end = prior_window_for(
        current_start,
        current_end,
        mode="range",
    )
    assert prior_start == datetime(2026, 4, 8)
    assert prior_end == datetime(2026, 4, 14, 23, 59, 59, 999999)


def test_prior_window_for_range_has_no_gap_at_boundary():
    """Regression for the 1-second gap: prior_end must be exactly 1
    microsecond before current_start, so the prior window's inclusive
    end abuts the current window's start with no dropped instant --
    a timestamp landing on the last microsecond of the prior day (as
    inclusive_date_bounds() produces for the current window) must not
    fall into the gap between the two windows."""
    current_start, current_end = inclusive_date_bounds("2026-04-15", "2026-04-21")
    _, prior_end = prior_window_for(
        current_start,
        current_end,
        mode="range",
    )
    assert prior_end == current_start - timedelta(microseconds=1)
    # No instant exists strictly between prior_end and current_start.
    assert prior_end + timedelta(microseconds=1) == current_start


def test_prior_window_for_duration_half_open():
    """--last 168h: prior_end exactly equals current_start (half-open)."""
    current_start = datetime(2026, 5, 4, 9, 30, 0)
    current_end = datetime(2026, 5, 11, 9, 30, 0)
    prior_start, prior_end = prior_window_for(
        current_start,
        current_end,
        mode="duration",
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
    test_prior_window_for_range_has_no_gap_at_boundary()
    test_prior_window_for_duration_half_open()
    test_prior_window_for_rejects_unknown_mode()
    print("OK")
