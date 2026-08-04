"""Tests for CSV summaries and the three HTML chart entry points."""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import summarize
import trend_data


FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parents[1]


def test_skill_documents_retrospective_time_analysis():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    report_template = (ROOT / "REPORT_TEMPLATE.md").read_text(encoding="utf-8")

    assert "turn_duration" in skill
    assert "--command /wrap" in skill
    assert "Slash command time" in report_template


def test_trend_data_reads_ranges_and_rejects_unknown_options(workspace_directory: Path):
    csv_path = workspace_directory / "sessions.csv"
    csv_path.write_text(
        "label,first_timestamp,cost_usd\n"
        "host-a,2026-03-02T10:00:00+00:00,1.25\n"
        "host-b,,2.00\n"
        "host-c,invalid,3.00\n"
        "host-d,2026-04-01T00:00:00+00:00,4.00\n",
        encoding="utf-8",
    )

    rows, skipped = trend_data.read_sessions_in_range(
        csv_path,
        datetime(2026, 3, 1),
        datetime(2026, 3, 31, 23, 59, 59),
    )
    assert len(rows) == 1
    assert rows[0]["_cost_usd_float"] == 1.25
    assert rows[0]["_parsed_timestamp"].tzinfo is None
    assert skipped == 2

    assert trend_data.inclusive_month_bounds("2026-12") == (
        datetime(2026, 12, 1),
        datetime(2026, 12, 31, 23, 59, 59, 999999),
    )
    assert trend_data.inclusive_date_bounds("2026-03-01", "2026-03-02") == (
        datetime(2026, 3, 1),
        datetime(2026, 3, 2, 23, 59, 59, 999999),
    )
    assert trend_data.bucket_index(datetime(2026, 2, 1), datetime(2026, 1, 1), "month") == 1
    assert trend_data.num_buckets(0, "day") == 1
    assert trend_data.num_buckets(8, "week") == 2
    assert trend_data.num_buckets(31, "month") == 2

    with pytest.raises(ValueError, match="unknown granularity"):
        trend_data.bucket_key(datetime(2026, 1, 1), "quarter")
    with pytest.raises(ValueError, match="unknown granularity"):
        trend_data.bucket_index(datetime(2026, 1, 1), datetime(2026, 1, 1), "quarter")
    with pytest.raises(ValueError, match="unknown granularity"):
        trend_data.num_buckets(1, "quarter")
    with pytest.raises(ValueError, match="must be"):
        trend_data.parse_last("")


def test_plot_trend_helpers_render_escaped_html(load_script):
    plot_trend = load_script("plot-trend.py")
    rows = [
        {"_parsed_timestamp": datetime(2026, 3, 1), "_cost_usd_float": 1.23456, "label": "b"},
        {"_parsed_timestamp": datetime(2026, 3, 1), "_cost_usd_float": 2.0, "label": "a</script>"},
        {"_parsed_timestamp": datetime(2026, 3, 2), "_cost_usd_float": 3.0, "label": "b"},
    ]
    buckets, costs, cumulative, counts = plot_trend.pivot_to_datasets(rows, "day")
    assert buckets == ["2026-03-01", "2026-03-02"]
    assert costs["b"] == [1.2346, 3.0]
    assert counts["a</script>"] == [1, 0]
    assert cumulative == [3.2346, 6.2346]
    assert plot_trend._label_color("host-a") in plot_trend.PALETTE

    page = plot_trend.render_html(
        range_label="<March>",
        bucket_granularity="day",
        buckets=buckets,
        per_label_costs=costs,
        per_label_counts=counts,
        cumulative=cumulative,
        inline=False,
    )
    assert "&lt;March&gt;" in page
    assert "a&lt;/script&gt;" in page
    assert r"<\/script>" in page


def test_plot_trend_main_writes_and_opens_chart(
    monkeypatch,
    workspace_directory: Path,
    load_script,
):
    plot_trend = load_script("plot-trend.py")
    output_path = workspace_directory / "trend.html"
    opened = []
    monkeypatch.setattr(plot_trend.webbrowser, "open", opened.append)
    monkeypatch.setattr(sys, "argv", [
        "plot-trend.py",
        "--month", "2026-03",
        "--bucket", "week",
        "--csv", str(FIXTURES / "sessions-demo.csv"),
        "--out", str(output_path),
        "--open",
    ])

    plot_trend.main()

    assert "Cost trend" in output_path.read_text(encoding="utf-8")
    assert opened == [output_path.resolve().as_uri()]


def test_plot_compare_helpers_cover_windows_buckets_and_rendering(load_script):
    plot_compare = load_script("plot-compare.py")
    parser = SimpleNamespace(error=lambda message: (_ for _ in ()).throw(ValueError(message)))
    month = SimpleNamespace(month="2026-03", start=None, end=None, last=None)
    start, end, mode, label, filename, span = plot_compare._resolve_current_window(month, parser)
    assert (mode, label, filename, span) == ("month", "2026-03", "2026-03", 31)
    assert start == datetime(2026, 3, 1)
    assert end == datetime(2026, 3, 31, 23, 59, 59, 999999)

    date_range = SimpleNamespace(month=None, start="2026-03-01", end="2026-03-02", last=None)
    assert plot_compare._resolve_current_window(date_range, parser)[2] == "range"
    duration = SimpleNamespace(month=None, start=None, end=None, last="24h")
    assert plot_compare._resolve_current_window(duration, parser)[2] == "duration"

    rows = [
        {"_parsed_timestamp": datetime(2026, 3, 1), "_cost_usd_float": 1.234},
        {"_parsed_timestamp": datetime(2026, 3, 5), "_cost_usd_float": 2.0},
    ]
    assert plot_compare.aggregate_per_bucket(rows, datetime(2026, 3, 1), "day", 2) == [1.23, 0.0]
    assert plot_compare.cumulative([1.23, 2.0]) == [1.23, 3.23]
    assert plot_compare.bucket_labels(start, datetime(2026, 2, 1), "day", 1)[0].startswith("Day 1")
    assert plot_compare.bucket_labels(start, datetime(2026, 2, 1), "week", 1)[0].startswith("Week 1")
    assert plot_compare.bucket_labels(start, datetime(2026, 2, 1), "month", 1)[0].startswith("Month 1")

    page = plot_compare.render_html(
        range_label="<range>",
        current_start=start,
        current_end=end,
        prior_start=datetime(2026, 2, 1),
        prior_end=datetime(2026, 2, 28, 23, 59, 59),
        current_total=1.23,
        prior_total=2.34,
        current_sessions=1,
        prior_sessions=2,
        labels=["</script>"],
        current_per_bucket=[1.23],
        current_cumulative_data=[1.23],
        prior_per_bucket=[2.34],
        prior_cumulative_data=[2.34],
        inline=False,
    )
    assert "&lt;range&gt;" in page
    assert r"<\/script>" in page


def test_plot_compare_main_writes_and_opens_chart(
    monkeypatch,
    workspace_directory: Path,
    load_script,
):
    plot_compare = load_script("plot-compare.py")
    output_path = workspace_directory / "compare.html"
    opened = []
    monkeypatch.setattr(plot_compare.webbrowser, "open", opened.append)
    monkeypatch.setattr(sys, "argv", [
        "plot-compare.py",
        "--month", "2026-03",
        "--bucket", "day",
        "--csv", str(FIXTURES / "sessions-demo.csv"),
        "--out", str(output_path),
        "--open",
    ])

    plot_compare.main()

    assert "Cost comparison" in output_path.read_text(encoding="utf-8")
    assert opened == [output_path.resolve().as_uri()]


def test_plot_session_resolves_collects_renders_and_runs(
    monkeypatch,
    workspace_directory: Path,
    load_script,
):
    plot_session = load_script("plot-session.py")
    projects = workspace_directory / "projects"
    slug = projects / "project"
    slug.mkdir(parents=True)
    parent = slug / "session-123.jsonl"
    session_entry = json.dumps({
        "type": "assistant",
        "timestamp": "2026-03-01T10:00:00Z",
        "message": {
            "id": "turn-one",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "usage": {"input_tokens": 100, "output_tokens": 20},
        },
    })
    parent.write_text(session_entry + "\n", encoding="utf-8")
    subagents = slug / "session-123" / "subagents"
    subagents.mkdir(parents=True)
    (subagents / "agent-one.jsonl").write_text(session_entry + "\n", encoding="utf-8")

    assert plot_session.resolve_session(str(parent), []) == (parent, "session-123")
    assert plot_session.resolve_session("session-1", [projects]) == (parent, "session-123")
    count, cost = plot_session.collect_subagent_summary(parent)
    assert count == 1
    assert cost > 0
    assert plot_session.collect_subagent_summary(slug / "missing.jsonl") == (0, 0.0)

    turns = list(plot_session.iter_assistant_turns(parent))
    cumulative = 0.0
    for turn in turns:
        cumulative += turn["cost_usd"]
        turn["cumulative_cost"] = cumulative
    turns[0]["model"] = "<synthetic></script>"
    page = plot_session.render_html(turns, count, cost, "<session>", "time", False)
    assert "&lt;session&gt;" in page
    assert r"<\/script>" in page

    output_path = workspace_directory / "session.html"
    opened = []
    monkeypatch.setattr(plot_session.webbrowser, "open", opened.append)
    monkeypatch.setattr(sys, "argv", [
        "plot-session.py", str(parent),
        "--x", "turn",
        "--out", str(output_path),
        "--open",
    ])
    plot_session.main()
    assert "Session session-123" in output_path.read_text(encoding="utf-8")
    assert opened == [output_path.resolve().as_uri()]

    with pytest.raises(SystemExit, match="no session"):
        plot_session.resolve_session("absent", [projects])

    second = slug / "session-456.jsonl"
    second.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit, match="ambiguous"):
        plot_session.resolve_session("session-", [projects])


def write_summary_csv(path: Path, cost_usd: str = "100"):
    fields = [
        "label", "session_date", "session_id", "cost_usd", "subagent_cost",
        "cache_hit_pct", "input_tokens", "output_tokens", "cache_read_tokens",
        "cache_write_tokens", "first_turn_input_tokens", "assistant_turns",
        "user_turns", "subagent_count", "top_tools",
        "active_time_seconds", "subagent_time_seconds", "timed_turns",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "label": "host-a",
            "session_date": "2026-03-01",
            "session_id": "session-a",
            "cost_usd": cost_usd,
            "subagent_cost": "10",
            "cache_hit_pct": "50",
            "input_tokens": "1000",
            "output_tokens": "100",
            "cache_read_tokens": "500",
            "cache_write_tokens": "250",
            "first_turn_input_tokens": "2048",
            "assistant_turns": "3",
            "user_turns": "2",
            "subagent_count": "1",
            "top_tools": "Read:1200,bad,Write:not-a-number",
            "active_time_seconds": "2700",
            "subagent_time_seconds": "300",
            "timed_turns": "3",
        })


def test_summarize_reports_paid_and_unpaid_views(monkeypatch, capsys, workspace_directory: Path):
    csv_path = workspace_directory / "sessions.csv"
    write_summary_csv(csv_path)
    assert summarize.parse_tools("") == {}
    assert summarize.parse_tools("Read:2,bad,Write:nope") == {"Read": 2}

    monkeypatch.setattr(sys, "argv", ["summarize.py", "--csv", str(csv_path), "--paid", "20"])
    summarize.main()
    paid_output = capsys.readouterr().out
    assert "SUBSCRIPTION LEVERAGE" in paid_output
    assert "SKILL/MEMORY CANDIDATES" in paid_output
    assert "Read" in paid_output
    assert "ACTIVE TIME" in paid_output
    assert "45m 00s" in paid_output

    monkeypatch.setattr(sys, "argv", ["summarize.py", "--csv", str(csv_path)])
    summarize.main()
    unpaid_output = capsys.readouterr().out
    assert "Prorated" not in unpaid_output
    assert "DAILY TOTALS" in unpaid_output


def test_summarize_accepts_timed_session_with_zero_cost(
    monkeypatch,
    capsys,
    workspace_directory: Path,
):
    csv_path = workspace_directory / "sessions.csv"
    write_summary_csv(csv_path, cost_usd="0")

    monkeypatch.setattr(sys, "argv", ["summarize.py", "--csv", str(csv_path)])
    summarize.main()

    output = capsys.readouterr().out
    assert "total $     0.00" in output
    assert "Parent active time (user wait): 45m 00s" in output


def test_summarize_reports_slash_command_time(
    monkeypatch,
    capsys,
    workspace_directory: Path,
):
    csv_path = workspace_directory / "sessions.csv"
    write_summary_csv(csv_path)
    commands_path = workspace_directory / "commands.csv"
    commands_path.write_text(
        "label,session_date,session_id,command,invocations,active_seconds,parent_path\n"
        "host-a,2026-03-01,session-a,/wrap,2,900,/tmp/session-a.jsonl\n"
        "host-a,2026-03-01,session-a,/review,1,60,/tmp/session-a.jsonl\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "argv", [
        "summarize.py",
        "--csv", str(csv_path),
        "--commands-csv", str(commands_path),
        "--command", "wrap",
    ])
    summarize.main()

    output = capsys.readouterr().out
    assert "SLASH COMMAND TIME" in output
    assert "/wrap" in output
    assert "2 timed invocations" in output
    assert "15m 00s" in output
    assert "COMMAND DETAIL: /wrap" in output

    assert summarize.normalize_command(" ") is None
    assert summarize.format_duration(3_661) == "1h 01m 01s"

    monkeypatch.setattr(sys, "argv", [
        "summarize.py",
        "--csv", str(csv_path),
        "--commands-csv", str(commands_path),
        "--command", "/missing",
    ])
    summarize.main()
    missing_output = capsys.readouterr().out
    assert "COMMAND DETAIL: /missing" in missing_output
    assert "No timed invocations found." in missing_output
