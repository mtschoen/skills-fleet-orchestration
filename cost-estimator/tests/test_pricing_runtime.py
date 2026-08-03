"""Coverage for transcript pricing and Chart.js runtime helpers."""

from __future__ import annotations

import json
from pathlib import Path

import chart_runtime
import pricing


def test_pricing_helpers_cover_model_families_and_date_aware_rates():
    assert pricing.model_family(None) is None
    assert pricing.model_family("CLAUDE-MYTHOS") == "fable"
    assert pricing.model_family("claude-opus-4-7[1m]") == "opus"
    assert pricing.model_family("claude-sonnet-5") == "sonnet5"
    assert pricing.model_family("claude-sonnet-4-6") == "sonnet"
    assert pricing.model_family("claude-haiku-4-5") == "haiku"
    assert pricing.model_family("unknown") is None

    assert pricing.rates_for("sonnet5", "2026-08-31T23:59:59Z") == (2.0, 10.0)
    assert pricing.rates_for("sonnet5", "2026-09-01T00:00:00Z") == (3.0, 15.0)
    assert pricing.parse_timestamp(None) is None
    assert pricing.parse_timestamp("not-a-date") is None
    assert pricing.parse_timestamp("2026-03-01T10:00:00Z").year == 2026

    assert pricing.cost_for_turn("unknown", 1, 2, 3, 4) == 0.0
    assert pricing.cost_for_turn("claude-opus-4-7", 1_000_000, 0, 0, 0) == 5.0
    assert pricing.cost_for_turn(
        "claude-sonnet-5", 1_000_000, 1_000_000, 1_000_000, 1_000_000,
        timestamp="2026-09-01T00:00:00Z",
    ) == 22.05


def test_iter_assistant_turns_filters_duplicates_and_collects_tools(
    workspace_directory: Path,
):
    transcript = workspace_directory / "session.jsonl"
    entries = [
        "",
        "not json",
        json.dumps(["not", "a", "mapping"]),
        json.dumps({"type": "user", "message": {"role": "user"}}),
        json.dumps({"type": "assistant", "message": {"role": "user"}}),
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-03-01T10:00:00Z",
            "message": {
                "id": "turn-1",
                "role": "assistant",
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "cache_read_input_tokens": 30,
                    "cache_creation_input_tokens": 40,
                },
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "tool_use", "name": "Read"},
                    {"type": "tool_use", "name": "Read"},
                    {"type": "tool_use"},
                    "not a block",
                ],
            },
        }),
        json.dumps({
            "type": "assistant",
            "message": {"id": "turn-1", "role": "assistant"},
        }),
        json.dumps({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "model": "claude-haiku-4-5",
                "content": "not a list",
            },
        }),
    ]
    transcript.write_text("\n".join(entries) + "\n", encoding="utf-8")

    turns = list(pricing.iter_assistant_turns(transcript))

    assert [turn["index"] for turn in turns] == [1, 2]
    assert turns[0]["top_tools"] == ["Read", "?"]
    assert turns[0]["cache_write_tokens"] == 40
    assert turns[0]["cost_usd"] > 0
    assert turns[1]["timestamp"] == ""


def test_chartjs_script_tags_support_cdn_and_inline(monkeypatch):
    chart_tag, adapter_tag = chart_runtime.chartjs_script_tags(
        inline=False,
        want_time_adapter=True,
    )
    assert chart_runtime.CHARTJS_CDN_URL in chart_tag
    assert chart_runtime.TIME_ADAPTER_CDN_URL in adapter_tag

    chart_tag, adapter_tag = chart_runtime.chartjs_script_tags(
        inline=False,
        want_time_adapter=False,
    )
    assert chart_runtime.CHARTJS_CDN_URL in chart_tag
    assert adapter_tag == ""

    monkeypatch.setattr(chart_runtime, "cached_download", lambda url, filename: b"js")
    chart_tag, adapter_tag = chart_runtime.chartjs_script_tags(
        inline=True,
        want_time_adapter=True,
    )
    assert chart_tag == "<script>js</script>"
    assert adapter_tag == "<script>js</script>"


def test_cached_download_writes_and_reuses_cache(monkeypatch, workspace_directory: Path):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exception_information):
            return False

        def read(self):
            return b"downloaded"

    calls = []

    def urlopen(url):
        calls.append(url)
        return Response()

    monkeypatch.setattr(Path, "home", classmethod(lambda path_class: workspace_directory))
    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    assert chart_runtime.cached_download("https://example.test/chart.js", "chart.js") == b"downloaded"
    assert chart_runtime.cached_download("https://example.test/chart.js", "chart.js") == b"downloaded"
    assert calls == ["https://example.test/chart.js"]
