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

import argparse
import csv
import hashlib
import json
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from chart_runtime import chartjs_script_tags  # noqa: E402
from roots import reports_directory  # noqa: E402
from trend_data import (  # noqa: E402
    bucket_key, auto_bucket, read_sessions_in_range,
    month_bounds, date_bounds,
)


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
    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))   # sums[label][bucket]
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))     # counts[label][bucket]
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
    # Sum from unrounded sums[] (not per_label_costs, whose values are already
    # rounded to 4dp) so round-down doesn't accumulate across many buckets.
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
    """Stable color from label hash.

    Picks from an 8-color palette via `md5(label)[0] % 8`. Distinct labels
    can collide once you have more than 8; for >8-machine setups, pick
    visually distinct labels and verify the rendered legend.
    """
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


DEFAULT_CSV_PATH = reports_directory() / "sessions.csv"
DEFAULT_OUT_DIR = reports_directory()


def main():
    parser = argparse.ArgumentParser(
        description="Render aggregate cost trend as an HTML chart."
    )
    range_group = parser.add_mutually_exclusive_group(required=True)
    range_group.add_argument("--month", help="YYYY-MM")
    range_group.add_argument("--start", help="YYYY-MM-DD start (requires --end)")
    parser.add_argument("--end", help="YYYY-MM-DD end (inclusive)")
    parser.add_argument("--bucket", choices=("day", "week", "month"),
                        default=None,
                        help="Bucket size (default: auto from range length)")
    parser.add_argument("--csv", default=str(DEFAULT_CSV_PATH),
                        help=f"sessions.csv path (default: {DEFAULT_CSV_PATH})")
    parser.add_argument("--inline-js", action="store_true")
    parser.add_argument("--out", default=None,
                        help=f"Output HTML path (default: {DEFAULT_OUT_DIR}/trend-<range>.html)")
    parser.add_argument("--open", dest="open_browser", action="store_true")
    arguments = parser.parse_args()

    if arguments.month and arguments.end:
        parser.error("--end requires --start, not --month")

    if arguments.month:
        try:
            range_start, range_end = month_bounds(arguments.month)
        except ValueError:
            parser.error(f"--month must be YYYY-MM, got {arguments.month!r}")
        range_label = arguments.month
        range_filename = arguments.month
        span_days = (range_end - range_start).days + 1
    else:
        if not arguments.end:
            parser.error("--start requires --end")
        range_start, range_end = date_bounds(arguments.start, arguments.end)
        range_label = f"{arguments.start} → {arguments.end}"
        range_filename = f"{arguments.start}_{arguments.end}"
        span_days = (range_end - range_start).days + 1

    granularity = arguments.bucket or auto_bucket(span_days)
    print(f"Range: {range_start.isoformat()} -> {range_end.isoformat()}",
          file=sys.stderr)
    print(f"Bucket: {granularity} (span={span_days} days)", file=sys.stderr)

    csv_path = Path(arguments.csv)
    if not csv_path.is_file():
        sys.exit(f"error: sessions.csv not found at {csv_path}. "
                 f"Run analyze-month.py first, or pass --csv <path>.")

    rows, skipped = read_sessions_in_range(csv_path, range_start, range_end)
    if not rows:
        # Probe overall span for a helpful error message
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            total_rows = 0
            min_ts = None
            max_ts = None
            for row in reader:
                total_rows += 1
                ts_string = row.get("first_timestamp") or ""
                if not ts_string:
                    continue
                try:
                    ts = datetime.fromisoformat(ts_string)
                    if ts.tzinfo is not None:
                        ts = ts.replace(tzinfo=None)
                except ValueError:
                    continue
                if min_ts is None or ts < min_ts:
                    min_ts = ts
                if max_ts is None or ts > max_ts:
                    max_ts = ts
        span_message = (f"{min_ts.isoformat()}...{max_ts.isoformat()}"
                        if min_ts else "(no parseable rows)")
        sys.exit(f"error: no sessions in range {range_start.date()} -> "
                 f"{range_end.date()} (csv has {total_rows} rows total, "
                 f"span {span_message}).")

    if skipped:
        print(f"note: skipped {skipped} rows with unparseable first_timestamp",
              file=sys.stderr)

    buckets, per_label_costs, cumulative, per_label_counts = pivot_to_datasets(
        rows, granularity,
    )

    html_text = render_html(
        range_label=range_label,
        bucket_granularity=granularity,
        buckets=buckets,
        per_label_costs=per_label_costs,
        per_label_counts=per_label_counts,
        cumulative=cumulative,
        inline=arguments.inline_js,
    )

    if arguments.out:
        output_path = Path(arguments.out)
    else:
        output_path = DEFAULT_OUT_DIR / f"trend-{range_filename}.html"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    print(f"Wrote {output_path}", file=sys.stderr)

    if arguments.open_browser:
        webbrowser.open(output_path.resolve().as_uri())


if __name__ == "__main__":
    main()
