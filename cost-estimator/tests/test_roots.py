"""Unit smoke for scripts/roots.py.

roots.py holds the root-resolution + date-bound + stats-file helpers shared
by analyze-month.py and stats_cache.py. Plain module name (no hyphen) so it
imports directly, unlike analyze-month.py.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import roots  # noqa: E402


def test_cli_roots_override_env():
    pairs = roots._resolve_roots(
        cli_roots=["/some/cli/path"],
        cli_labels=["host-a"],
        env_value="host-a:/x,host-b:/y",
    )
    assert pairs == [("host-a", Path("/some/cli/path"))]


def test_env_used_when_no_cli():
    pairs = roots._resolve_roots(
        cli_roots=[],
        cli_labels=[],
        env_value="host-a:/x,host-b:/y",
    )
    assert pairs == [("host-a", Path("/x")), ("host-b", Path("/y"))]


def test_default_when_no_cli_no_env():
    pairs = roots._resolve_roots(cli_roots=[], cli_labels=[], env_value=None)
    assert len(pairs) == 1
    assert pairs[0][0] == "local"
    assert pairs[0][1] == Path.home() / ".claude" / "projects"


def test_windows_drive_letter_in_env_path():
    """First colon is the delimiter; rest is the path (includes C:)."""
    pairs = roots._resolve_roots(
        cli_roots=[], cli_labels=[],
        env_value="host-a:C:/Users/someone/.claude/projects",
    )
    assert pairs == [("host-a", Path("C:/Users/someone/.claude/projects"))]


def test_env_malformed_raises():
    try:
        roots._resolve_roots(cli_roots=[], cli_labels=[], env_value="no_colon_entry")
    except SystemExit as exit_info:
        assert "malformed" in str(exit_info.code)
    else:
        raise AssertionError("expected SystemExit")


def test_stats_file_for_sibling_of_projects():
    """stats-cache.json sits next to the projects/ dir, one level up."""
    assert roots.stats_file_for(Path("/home/x/.claude/projects")) == \
        Path("/home/x/.claude/stats-cache.json")
    assert roots.stats_file_for(Path(r"Y:/.claude/projects")) == \
        Path(r"Y:/.claude/stats-cache.json")


def test_month_bounds_basic():
    start, end = roots.month_bounds("2026-04")
    assert start == datetime(2026, 4, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 5, 1, tzinfo=timezone.utc)


def test_month_bounds_december_rolls_year():
    start, end = roots.month_bounds("2026-12")
    assert start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert end == datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_date_bounds_end_is_exclusive_next_day():
    start, end = roots.date_bounds("2026-04-01", "2026-04-30")
    assert start == datetime(2026, 4, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 5, 1, tzinfo=timezone.utc)


def test_reports_directory_default_is_outside_skill_tree(monkeypatch):
    monkeypatch.delenv("AGENTS_COST_REPORTS_DIR", raising=False)
    result = roots.reports_directory()
    assert result == Path.home() / ".claude" / "cost-estimator" / "reports"


def test_reports_directory_environment_override(monkeypatch):
    monkeypatch.setenv("AGENTS_COST_REPORTS_DIR", "/custom/spot")
    assert roots.reports_directory() == Path("/custom/spot")


def test_reports_directory_override_expands_user(monkeypatch):
    monkeypatch.setenv("AGENTS_COST_REPORTS_DIR", "~/elsewhere")
    assert roots.reports_directory() == Path.home() / "elsewhere"


if __name__ == "__main__":
    test_cli_roots_override_env()
    test_env_used_when_no_cli()
    test_default_when_no_cli_no_env()
    test_windows_drive_letter_in_env_path()
    test_env_malformed_raises()
    test_stats_file_for_sibling_of_projects()
    test_month_bounds_basic()
    test_month_bounds_december_rolls_year()
    test_date_bounds_end_is_exclusive_next_day()
    print("OK")
