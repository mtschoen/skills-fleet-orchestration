"""Unit smoke for _resolve_roots() in analyze-month.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    """analyze-month.py has a hyphen; import via spec loader."""
    spec = importlib.util.spec_from_file_location(
        "analyze_month",
        Path(__file__).parent.parent / "scripts" / "analyze-month.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["analyze_month"] = module
    spec.loader.exec_module(module)
    return module


def test_cli_roots_override_env(monkeypatch_env=None):
    am = _load_module()
    pairs = am._resolve_roots(
        cli_roots=["/some/cli/path"],
        cli_labels=["host-a"],
        env_value="host-a:/x,host-b:/y",
    )
    assert pairs == [("host-a", Path("/some/cli/path"))]


def test_env_used_when_no_cli():
    am = _load_module()
    pairs = am._resolve_roots(
        cli_roots=[],
        cli_labels=[],
        env_value="host-a:/x,host-b:/y",
    )
    assert pairs == [("host-a", Path("/x")), ("host-b", Path("/y"))]


def test_default_when_no_cli_no_env():
    am = _load_module()
    pairs = am._resolve_roots(cli_roots=[], cli_labels=[], env_value=None)
    assert len(pairs) == 1
    assert pairs[0][0] == "local"
    assert pairs[0][1] == Path.home() / ".claude" / "projects"


def test_windows_drive_letter_in_env_path():
    """First colon is the delimiter; rest is the path (includes C:)."""
    am = _load_module()
    pairs = am._resolve_roots(
        cli_roots=[], cli_labels=[],
        env_value="host-a:C:/Users/mtsch/.claude/projects",
    )
    assert pairs == [("host-a", Path("C:/Users/mtsch/.claude/projects"))]


def test_env_malformed_raises():
    am = _load_module()
    try:
        am._resolve_roots(cli_roots=[], cli_labels=[], env_value="no_colon_entry")
    except SystemExit as exit_info:
        assert "malformed" in str(exit_info.code)
    else:
        raise AssertionError("expected SystemExit")


if __name__ == "__main__":
    test_cli_roots_override_env()
    test_env_used_when_no_cli()
    test_default_when_no_cli_no_env()
    test_windows_drive_letter_in_env_path()
    test_env_malformed_raises()
    print("OK")
