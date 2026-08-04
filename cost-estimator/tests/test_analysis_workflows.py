"""Integration coverage for analysis, cache TTL, and stats reconciliation."""

from __future__ import annotations

import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import cache_ttl
import stats_cache


FIXTURES = Path(__file__).parent / "fixtures"


def transcript_lines(
    identifier_prefix: str = "turn",
    *,
    include_non_mapping: bool = True,
) -> list[str]:
    """Return a representative parent transcript with duplicates and noise."""

    lines = [
        "",
        "not json",
        json.dumps(["not", "a", "mapping"]),
        json.dumps({"type": "progress", "timestamp": "2026-03-01T09:00:00Z"}),
        json.dumps({
            "type": "user",
            "timestamp": "2026-03-01T09:30:00Z",
            "isCompactSummary": True,
            "message": {"role": "user"},
        }),
        json.dumps({
            "type": "system",
            "subtype": "local_command",
            "timestamp": "2026-03-01T09:31:00Z",
            "content": "<command-name>/wrap</command-name>",
        }),
        json.dumps({
            "type": "system",
            "subtype": "turn_duration",
            "timestamp": "2026-03-01T09:31:01Z",
            "durationMs": "invalid",
        }),
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-03-01T10:00:00Z",
            "message": {
                "id": f"{identifier_prefix}-1",
                "role": "assistant",
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 1_000_000,
                    "output_tokens": 10_000,
                    "cache_read_input_tokens": 1_000,
                    "cache_creation_input_tokens": 10_000,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": 2_000,
                        "ephemeral_1h_input_tokens": 8_000,
                    },
                },
                "content": [
                    {"type": "tool_use", "name": "Read"},
                    {"type": "tool_use"},
                    {"type": "text", "text": "done"},
                ],
            },
        }),
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-03-01T10:00:00Z",
            "message": {"id": f"{identifier_prefix}-1", "role": "assistant"},
        }),
        json.dumps({
            "type": "system",
            "subtype": "turn_duration",
            "timestamp": "2026-03-01T10:00:01Z",
            "uuid": f"{identifier_prefix}-duration-1",
            "durationMs": 1_800_000,
        }),
        json.dumps({
            "type": "system",
            "subtype": "turn_duration",
            "timestamp": "2026-03-01T10:00:01Z",
            "uuid": f"{identifier_prefix}-duration-1",
            "durationMs": 1_800_000,
        }),
        json.dumps({
            "type": "user",
            "timestamp": "2026-03-01T10:00:02Z",
            "isMeta": True,
            "message": {
                "role": "user",
                "content": "<command-message>review</command-message>"
                           "<command-name>/review</command-name>",
            },
        }),
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-03-01T10:06:00Z",
            "message": {
                "id": f"{identifier_prefix}-2",
                "role": "assistant",
                "model": "claude-sonnet-5",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 200,
                    "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 6_000,
                    "cache_creation": {"ephemeral_5m_input_tokens": 6_000},
                },
                "content": "not a list",
            },
        }),
        json.dumps({
            "type": "system",
            "subtype": "turn_duration",
            "timestamp": "2026-03-01T10:06:01Z",
            "uuid": f"{identifier_prefix}-duration-2",
            "durationMs": 360_000,
        }),
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-03-01T10:07:00Z",
            "message": {"id": f"{identifier_prefix}-wrong", "role": "user"},
        }),
    ]
    if not include_non_mapping:
        lines.remove(json.dumps(["not", "a", "mapping"]))
    return lines


def write_transcript(
    path: Path,
    identifier_prefix: str = "turn",
    *,
    include_non_mapping: bool = True,
):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(transcript_lines(
            identifier_prefix,
            include_non_mapping=include_non_mapping,
        )) + "\n",
        encoding="utf-8",
    )


def test_analyze_process_file_and_discovery_cover_edge_cases(
    workspace_directory: Path,
    load_script,
):
    analyze_month = load_script("analyze-month.py")
    projects = workspace_directory / "projects"
    parent = projects / "slug" / "session.jsonl"
    subagent = projects / "slug" / "session" / "subagents" / "agent-one.jsonl"
    write_transcript(parent)
    write_transcript(subagent, "subagent")
    (projects / "not-a-directory").write_text("ignored", encoding="utf-8")

    totals = analyze_month.process_file(parent, "session", False)
    assert totals is not None
    assert totals.assistant_turns == 2
    assert totals.user_turns == 2
    assert totals.had_compact is True
    assert totals.first_turn_input_tokens == 1_011_000
    assert totals.tool_calls == {"Read": 1, "?": 1}
    assert totals.cost_usd > 5
    assert totals.active_time_ms == 2_160_000
    assert totals.timed_turns == 2
    assert totals.command_time_ms == {"/review": 360_000}
    assert totals.command_invocations == {"/review": 1}
    assert analyze_month._worker((str(parent), "session", False)).assistant_turns == 2

    assert analyze_month.command_name_from([
        {"type": "text", "text": "<command-message>Wrap now</command-message>"},
        {"type": "tool_result", "content": "ignored"},
    ]) == "/wrap"
    assert analyze_month.command_name_from("/REVIEW details") == "/review"
    assert analyze_month.command_name_from({"text": "/ignored"}) is None
    assert analyze_month.command_name_from(" ") is None
    assert analyze_month._normalize_command(" ") is None
    assert analyze_month._duration_ms(True) is None
    assert analyze_month._duration_ms("invalid") is None
    assert analyze_month._duration_ms(-1) is None

    empty = workspace_directory / "empty.jsonl"
    empty.write_text("not json\n", encoding="utf-8")
    assert analyze_month.process_file(empty, "empty", False) is None
    assert analyze_month.process_file(workspace_directory / "missing.jsonl", "missing", False) is None
    assert analyze_month.discover_files(workspace_directory / "absent") == []

    discovered = analyze_month.discover_files(projects)
    assert {(path.name, is_subagent) for path, _, is_subagent in discovered} == {
        ("session.jsonl", False),
        ("agent-one.jsonl", True),
    }


def test_analyze_process_file_clears_commands_for_skipped_durations(
    workspace_directory: Path,
    load_script,
):
    analyze_month = load_script("analyze-month.py")
    transcript = workspace_directory / "skipped-durations.jsonl"
    entries = [
        {"type": "system", "subtype": "local_command", "content": "/invalid"},
        {"type": "system", "subtype": "turn_duration", "durationMs": "invalid"},
        {"type": "system", "subtype": "turn_duration", "uuid": "valid-1", "durationMs": 100},
        {"type": "system", "subtype": "local_command", "content": "/missing"},
        {"type": "system", "subtype": "turn_duration"},
        {"type": "system", "subtype": "turn_duration", "uuid": "valid-2", "durationMs": 200},
        {"type": "system", "subtype": "turn_duration", "uuid": "duplicate", "durationMs": 300},
        {"type": "system", "subtype": "local_command", "content": "/duplicate"},
        {"type": "system", "subtype": "turn_duration", "uuid": "duplicate", "durationMs": 300},
        {"type": "system", "subtype": "turn_duration", "uuid": "valid-3", "durationMs": 400},
        {"type": "system", "subtype": "local_command", "content": "/absent"},
        {"type": "assistant", "message": {"role": "assistant"}},
        {"type": "user", "message": {"role": "user", "content": "next turn"}},
        {"type": "assistant", "message": {"role": "assistant"}},
        {"type": "system", "subtype": "turn_duration", "uuid": "valid-4", "durationMs": 500},
        {"type": "system", "subtype": "local_command", "content": "/tools"},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result"}]}},
        {"type": "system", "subtype": "turn_duration", "uuid": "valid-5", "durationMs": 600},
    ]
    transcript.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n",
        encoding="utf-8",
    )

    totals = analyze_month.process_file(transcript, "session", False)

    assert totals is not None
    assert totals.active_time_ms == 2_100
    assert totals.timed_turns == 6
    assert totals.command_time_ms == {"/tools": 600}
    assert totals.command_invocations == {"/tools": 1}


def test_analyze_main_writes_session_and_daily_reports(
    monkeypatch,
    capsys,
    workspace_directory: Path,
    load_script,
):
    analyze_month = load_script("analyze-month.py")
    claude_directory = workspace_directory / ".claude"
    projects = claude_directory / "projects"
    parent = projects / "slug" / "session.jsonl"
    subagent = projects / "slug" / "session" / "subagents" / "agent-one.jsonl"
    write_transcript(parent)
    write_transcript(subagent, "subagent")
    (claude_directory / "stats-cache.json").write_text(
        (FIXTURES / "stats-cache-demo.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    output_directory = workspace_directory / "reports"

    monkeypatch.setattr(analyze_month, "ProcessPoolExecutor", ThreadPoolExecutor)
    monkeypatch.setattr(sys, "argv", [
        "analyze-month.py", str(projects),
        "--month", "2026-03",
        "--label", "local",
        "--workers", "1",
        "--out", str(output_directory),
    ])

    analyze_month.main()

    standard_output = capsys.readouterr().out
    assert "MARCH" not in standard_output
    assert "2026-03 SUMMARY" in standard_output
    assert "Least cache-friendly" in standard_output
    assert "COVERAGE vs /stats" in standard_output

    with (output_directory / "sessions.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["session_id"] == "session"
    assert rows[0]["subagent_count"] == "1"
    assert rows[0]["had_compact"] == "True"
    assert rows[0]["active_time_seconds"] == "2160.0"
    assert rows[0]["subagent_time_seconds"] == "2160.0"
    assert rows[0]["timed_turns"] == "2"
    assert (output_directory / "daily.csv").is_file()

    with (output_directory / "commands.csv").open(newline="", encoding="utf-8") as handle:
        command_rows = list(csv.DictReader(handle))
    assert command_rows == [
        {
            "label": "local",
            "session_date": "2026-03-01",
            "session_id": "session",
            "command": "/review",
            "invocations": "1",
            "active_seconds": "360.0",
            "parent_path": str(parent),
        },
    ]

    with (output_directory / "daily.csv").open(newline="", encoding="utf-8") as handle:
        daily_rows = list(csv.DictReader(handle))
    assert daily_rows[0]["active_seconds"] == "2160.0"


def test_cache_ttl_parses_turns_and_prints_behavioral_report(
    monkeypatch,
    capsys,
    workspace_directory: Path,
):
    projects = workspace_directory / "projects"
    transcript = projects / "slug" / "session.jsonl"
    write_transcript(transcript, include_non_mapping=False)

    turns = cache_ttl.turns_of(transcript)
    assert len(turns) == 3
    assert turns[0]["ephemeral_1h"] == 8_000
    assert cache_ttl.bucket_for(-1) is None
    assert cache_ttl.parent_transcripts([("local", projects)]) == [str(transcript)]

    monkeypatch.setattr(sys, "argv", ["cache_ttl.py", str(projects), "--label", "local"])
    cache_ttl.main()
    output = capsys.readouterr().out
    assert "ephemeral_5m total" in output
    assert "5-10m" in output
    assert "100.0%" in output


def test_stats_cache_combines_roots_formats_warnings_and_runs_cli(
    monkeypatch,
    capsys,
    workspace_directory: Path,
):
    claude_directory = workspace_directory / ".claude"
    projects = claude_directory / "projects"
    transcript = projects / "slug" / "session.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        (FIXTURES / "transcript-demo.jsonl").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    stats_path = claude_directory / "stats-cache.json"
    stats_path.write_text(
        (FIXTURES / "stats-cache-demo.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    end = datetime(2026, 4, 1, tzinfo=timezone.utc)

    walked = stats_cache.walk_transcripts_daily_in_out(projects, dedupe=False)
    assert walked["2026-03-01"] == 75_000
    combined, per_root = stats_cache.coverage_for_roots(
        [("local", projects), ("missing", workspace_directory / "missing-projects")],
        start,
        end,
    )
    assert combined.stats_total == 1_590_000
    assert len(per_root) == 2
    warning = stats_cache.format_warning(combined)
    assert warning is not None
    assert "Cleared days" in warning
    assert stats_cache.format_warning(
        stats_cache.Coverage(1, 1, 1.0, [], 0, {}),
    ) is None

    many_days = [f"2026-03-{day:02d}" for day in range(1, 13)]
    long_warning = stats_cache.format_warning(
        stats_cache.Coverage(100, 1, 0.01, many_days, 99, {}),
    )
    assert long_warning is not None
    assert "+2 more" in long_warning

    stats_cache._print_model_usage({}, "empty")
    stats_cache._print_day_table(stats_cache.Coverage(0, 0, None, [], 0, {}), "empty")
    monkeypatch.setattr(sys, "argv", [
        "stats_cache.py", str(projects),
        "--month", "2026-03",
        "--label", "local",
        "--threshold", "0.90",
    ])
    stats_cache.main()
    output = capsys.readouterr().out
    assert "stats-cache reconciliation for 2026-03" in output
    assert "modelUsage inventory" in output
    assert "coverage warning" in output


def test_stats_cache_partial_classification_and_healthy_warning():
    statuses = stats_cache.classify_days(
        {"2026-03-01": 10_000},
        {"2026-03-01": 40_000},
        cleared_floor=50_000,
        match_floor=1,
        match_ratio=0.01,
    )
    assert statuses == {"2026-03-01": "partial"}
