"""Render aggregate Claude Code cost trend across sessions as an HTML chart.

Reads sessions.csv (the artifact written by analyze-month.py), buckets
sessions by their first_timestamp into day/week/month bins, stacks the
per-bucket cost by machine label, and overlays a cumulative-total line
on a right y-axis. Visual idiom matches plot-session.py.

Usage:
    python plot-trend.py
        (--month YYYY-MM | --start YYYY-MM-DD --end YYYY-MM-DD)
        [--bucket {day,week,month}]
        [--csv <path>]
        [--inline-js]
        [--out <path>]
        [--open]
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from chart_runtime import chartjs_script_tags  # noqa: E402


def bucket_key(timestamp: datetime, granularity: str) -> str:
    """Return a stable string key for grouping by day, week, or month.

    Keys are designed to sort lexically into chronological order so
    `sorted(bucket_set)` in the pivot step yields the right x-axis
    ordering without parsing.

    - day:   "2026-04-12"
    - week:  "YYYY-Www" using ISO week numbering (year may differ from
             timestamp.year near Jan/Dec boundaries)
    - month: "2026-04"  (locale-immune, lexically sortable; display
             formatting like "Apr 2026" happens at render time)
    """
    if granularity == "day":
        return timestamp.strftime("%Y-%m-%d")
    if granularity == "week":
        iso_year, iso_week, _ = timestamp.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if granularity == "month":
        return timestamp.strftime("%Y-%m")
    raise ValueError(f"unknown granularity: {granularity!r}")


def auto_bucket(days: int) -> str:
    """Pick a bucket granularity from a date-range span."""
    if days <= 14:
        return "day"
    if days <= 90:
        return "week"
    return "month"


def read_sessions_in_range(csv_path: Path, range_start: datetime,
                           range_end: datetime):
    """Read rows of sessions.csv whose first_timestamp falls in
    [range_start, range_end] (inclusive).

    Boundaries should be NAIVE datetimes (no tzinfo). The CSV stores
    tz-aware timestamps; this function strips tzinfo on parse so the
    range comparison works without the caller needing to know.

    Returns (rows, skipped) where:
      - rows: list of dicts with two extra fields per row:
          "_parsed_timestamp" (datetime, naive) and "_cost_usd_float" (float)
      - skipped: count of rows with missing/unparseable first_timestamp
    """
    rows = []
    skipped = 0
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timestamp_string = row.get("first_timestamp") or ""
            if not timestamp_string:
                skipped += 1
                continue
            try:
                timestamp = datetime.fromisoformat(timestamp_string)
            except ValueError:
                skipped += 1
                continue
            # Drop tzinfo so callers can pass naive boundary datetimes
            # (argparse-derived from "YYYY-MM-DD" strings). The trend
            # chart treats sessions in local wall-clock anyway.
            if timestamp.tzinfo is not None:
                timestamp = timestamp.replace(tzinfo=None)
            if range_start <= timestamp <= range_end:
                row["_parsed_timestamp"] = timestamp
                row["_cost_usd_float"] = float(row.get("cost_usd") or 0)
                rows.append(row)
    return rows, skipped


def pivot_to_datasets(rows: list[dict], granularity: str):
    """Pivot per-row costs into per-(label, bucket) totals + a cumulative
    line.

    Returns (buckets_sorted, per_label_costs, cumulative, per_label_counts):
      - buckets_sorted: list[str], the unique bucket keys present in
        the data, in chronological (lexical) order.
      - per_label_costs: dict[label, list[float]] — each list aligned
        with buckets_sorted, zero-filled where the (label, bucket) had
        no sessions.
      - cumulative: list[float] aligned with buckets_sorted, running
        total across all labels.
      - per_label_counts: dict[label, list[int]] — session counts per
        bucket, used by hover tooltips at render time.
    """
    sums = defaultdict(lambda: defaultdict(float))     # sums[label][bucket]
    counts = defaultdict(lambda: defaultdict(int))     # counts[label][bucket]
    bucket_set = set()
    label_set = set()
    for row in rows:
        key = bucket_key(row["_parsed_timestamp"], granularity)
        label = row["label"]
        sums[label][key] += row["_cost_usd_float"]
        counts[label][key] += 1
        bucket_set.add(key)
        label_set.add(label)

    buckets_sorted = sorted(bucket_set)
    labels_sorted = sorted(label_set)
    per_label_costs = {
        label: [round(sums[label].get(bucket, 0.0), 4) for bucket in buckets_sorted]
        for label in labels_sorted
    }
    per_label_counts = {
        label: [counts[label].get(bucket, 0) for bucket in buckets_sorted]
        for label in labels_sorted
    }

    cumulative = []
    running = 0.0
    for bucket in buckets_sorted:
        for label in labels_sorted:
            running += sums[label].get(bucket, 0.0)
        cumulative.append(round(running, 4))

    return buckets_sorted, per_label_costs, cumulative, per_label_counts


PALETTE = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
    "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
]


def _label_color(label: str) -> str:
    """Stable color from label hash; collides past 8 distinct labels."""
    digest = hashlib.md5(label.encode("utf-8")).digest()
    return PALETTE[digest[0] % len(PALETTE)]


# Filled via str.format(). Literal `{` / `}` in JS/CSS doubled to `{{` / `}}`.
HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Trend {range_label}</title>
{chartjs_script_tag}
<style>
  html, body {{ height: 100%; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 12px; color: #222; }}
  h1 {{ margin: 0 0 8px 0; font-size: 18px; }}
  .meta {{ font-family: ui-monospace, "Cascadia Mono", Menlo, monospace;
          font-size: 12px; color: #555; margin-bottom: 16px; }}
  .meta span {{ display: inline-block; margin-right: 18px; }}
  .chart-wrap {{ position: relative; width: 100%; height: 70vh; min-height: 420px; }}
  canvas {{ width: 100% !important; height: 100% !important; }}
  .footnote {{ font-size: 11px; color: #888; margin-top: 12px; }}
</style>
</head>
<body>
<h1>Cost trend — {range_label}</h1>
<div class="meta">
  <span>Bucket: {bucket_granularity}</span>
  <span>Total: ${total_cost:.4f}</span>
  <span>Sessions: {total_sessions}</span>
  <span>Machines: {machines_summary}</span>
</div>
<div class="chart-wrap"><canvas id="chart"></canvas></div>
<div class="footnote">
  Aggregates per-session costs from sessions.csv; subagent costs are folded
  into their parent session's total (no separate subagent series).
</div>
<script>
const BUCKETS = {buckets_json};
const PER_LABEL_COSTS = {per_label_costs_json};
const PER_LABEL_COUNTS = {per_label_counts_json};
const PER_LABEL_COLORS = {per_label_colors_json};
const CUMULATIVE = {cumulative_json};

const labels = Object.keys(PER_LABEL_COSTS);
const datasets = labels.map(label => ({{
  type: "bar",
  label: label,
  data: PER_LABEL_COSTS[label],
  backgroundColor: PER_LABEL_COLORS[label],
  borderColor: PER_LABEL_COLORS[label],
  stack: "cost",
  yAxisID: "y",
}}));
datasets.push({{
  type: "line",
  label: "Cumulative",
  data: CUMULATIVE,
  borderColor: "#333",
  backgroundColor: "rgba(0,0,0,0)",
  borderWidth: 2,
  tension: 0.2,
  pointRadius: 0,
  yAxisID: "y1",
}});

new Chart(document.getElementById("chart"), {{
  data: {{ labels: BUCKETS, datasets: datasets }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    scales: {{
      x: {{ stacked: true, type: "category" }},
      y: {{ stacked: true, position: "left", beginAtZero: true,
           title: {{ display: true, text: "Cost ($)" }} }},
      y1: {{ position: "right", beginAtZero: true,
            grid: {{ drawOnChartArea: false }},
            title: {{ display: true, text: "Cumulative ($)" }} }},
    }},
    plugins: {{
      tooltip: {{
        callbacks: {{
          afterLabel: (item) => {{
            if (item.dataset.type !== "bar") return "";
            const label = item.dataset.label;
            const count = PER_LABEL_COUNTS[label][item.dataIndex];
            return `${{count}} session${{count === 1 ? "" : "s"}}`;
          }},
        }},
      }},
    }},
  }},
}});
</script>
</body>
</html>
"""


def render_html(*, range_label: str, bucket_granularity: str,
                buckets: list[str], per_label_costs: dict,
                per_label_counts: dict, cumulative: list[float],
                inline: bool) -> str:
    chartjs_script_tag, _ = chartjs_script_tags(inline=inline,
                                                want_time_adapter=False)
    total_cost = cumulative[-1] if cumulative else 0.0
    total_sessions = sum(sum(counts) for counts in per_label_counts.values())
    per_label_totals = {
        label: (round(sum(costs), 2), sum(per_label_counts[label]))
        for label, costs in per_label_costs.items()
    }
    machines_summary = ", ".join(
        f"{label} (${cost:.2f}, {count})"
        for label, (cost, count) in sorted(per_label_totals.items())
    )
    per_label_colors = {label: _label_color(label) for label in per_label_costs}

    return HTML_TEMPLATE.format(
        range_label=range_label,
        bucket_granularity=bucket_granularity,
        total_cost=total_cost,
        total_sessions=total_sessions,
        machines_summary=machines_summary or "(none)",
        chartjs_script_tag=chartjs_script_tag,
        buckets_json=json.dumps(buckets).replace("</", "<\\/"),
        per_label_costs_json=json.dumps(per_label_costs).replace("</", "<\\/"),
        per_label_counts_json=json.dumps(per_label_counts).replace("</", "<\\/"),
        per_label_colors_json=json.dumps(per_label_colors).replace("</", "<\\/"),
        cumulative_json=json.dumps(cumulative).replace("</", "<\\/"),
    )
