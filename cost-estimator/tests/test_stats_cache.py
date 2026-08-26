"""Unit tests for scripts/stats_cache.py.

Covers the pure reconciliation core: stats-cache parsing, per-day in+out
extraction, transcript dedup-walk, day classification, and range coverage.
Verified against fixtures in tests/fixtures/. The CLI report and the
multi-root orchestration (which touch the real filesystem + a second
transcript walk) are exercised in the real-data verification step, not here.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import stats_cache  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
STATS_FIXTURE = FIXTURES / "stats-cache-demo.json"
TRANSCRIPT_FIXTURE = FIXTURES / "transcript-demo.jsonl"


def test_load_stats_missing_file_returns_none():
    assert stats_cache.load_stats(FIXTURES / "does-not-exist.json") is None


def test_load_stats_reads_metadata():
    stats = stats_cache.load_stats(STATS_FIXTURE)
    assert stats is not None
    assert stats["lastComputedDate"] == "2026-03-15"


def test_stats_daily_in_out_sums_models_per_day():
    stats = stats_cache.load_stats(STATS_FIXTURE)
    daily = stats_cache.stats_daily_in_out(stats)
    # 800000 + 200000 across two models on the first day
    assert daily["2026-03-01"] == 1_000_000
    assert daily["2026-03-02"] == 60_000
    assert daily["2026-04-05"] == 90_000


def test_daily_in_out_of_file_dedupes_by_message_id():
    daily = stats_cache.daily_in_out_of_file(TRANSCRIPT_FIXTURE)
    # id "a" appears twice (25000 each) but must be counted once; + id "b" 25000
    assert daily["2026-03-01"] == 50_000
    assert daily["2026-03-02"] == 60_000
    assert daily["2026-03-03"] == 30_000
    assert daily["2026-04-05"] == 90_000


def test_daily_in_out_of_file_raw_counts_duplicate_snapshots():
    """Raw mode (dedupe=False) counts every assistant line, matching how
    /stats dailyModelTokens is computed (non-deduped). Verified: raw
    transcript in+out == /stats per-day to the token. id 'a' appears twice."""
    daily = stats_cache.daily_in_out_of_file(TRANSCRIPT_FIXTURE, dedupe=False)
    assert daily["2026-03-01"] == 75_000  # 25000 x3 (the duplicate counts)
    assert daily["2026-03-02"] == 60_000


def test_classify_days_flags_cleared_match_partial():
    stats_daily = {
        "2026-03-01": 1_000_000,  # transcripts gutted -> CLEARED
        "2026-03-02": 60_000,  # equal -> match
        "2026-03-03": 30_000,  # below cleared floor, equal -> match
        "2026-03-10": 500_000,  # nothing survived -> CLEARED
    }
    tx_daily = {
        "2026-03-01": 50_000,
        "2026-03-02": 60_000,
        "2026-03-03": 30_000,
        "2026-03-10": 0,
    }
    status = stats_cache.classify_days(stats_daily, tx_daily)
    assert status["2026-03-01"] == "cleared"
    assert status["2026-03-02"] == "match"
    assert status["2026-03-03"] == "match"
    assert status["2026-03-10"] == "cleared"


def test_coverage_for_march_range_excludes_april_and_flags_cleared():
    stats = stats_cache.load_stats(STATS_FIXTURE)
    stats_daily = stats_cache.stats_daily_in_out(stats)
    tx_daily = {
        "2026-03-01": 50_000,
        "2026-03-02": 60_000,
        "2026-03-03": 30_000,
        "2026-04-05": 90_000,  # outside the March window, must be excluded
    }
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end = datetime(2026, 4, 1, tzinfo=timezone.utc)  # exclusive
    cov = stats_cache.coverage(stats_daily, tx_daily, start, end)
    assert cov.stats_total == 1_590_000  # 1,000,000+60,000+30,000+500,000
    assert cov.transcript_total == 140_000  # 50,000+60,000+30,000 (April excluded)
    assert cov.cleared_days == ["2026-03-01", "2026-03-10"]
    assert cov.cleared_tokens == 1_500_000
    assert abs(cov.coverage_pct - (140_000 / 1_590_000)) < 1e-9


def test_coverage_pct_none_when_no_stats_in_range():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 2, 1, tzinfo=timezone.utc)
    cov = stats_cache.coverage({"2026-03-01": 100}, {"2026-03-01": 100}, start, end)
    assert cov.stats_total == 0
    assert cov.coverage_pct is None
    assert cov.cleared_days == []


if __name__ == "__main__":
    test_load_stats_missing_file_returns_none()
    test_load_stats_reads_metadata()
    test_stats_daily_in_out_sums_models_per_day()
    test_daily_in_out_of_file_dedupes_by_message_id()
    test_daily_in_out_of_file_raw_counts_duplicate_snapshots()
    test_classify_days_flags_cleared_match_partial()
    test_coverage_for_march_range_excludes_april_and_flags_cleared()
    test_coverage_pct_none_when_no_stats_in_range()
    print("OK")
