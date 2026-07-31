"""Render any window vs the same-length prior window as an overlaid
Chart.js HTML chart (grouped bars per bucket + twin cumulative lines).

Reads sessions.csv (the artifact written by analyze-month.py), filters
each row into the current window or the prior window by its
first_timestamp, buckets sessions by their position WITHIN their window
(bucket-index, not calendar date), and renders the overlay.

Usage:
    python plot-compare.py
        (--month YYYY-MM | --start YYYY-MM-DD --end YYYY-MM-DD | --last <Nh|Nd>)
        [--bucket {day,week,month}]
        [--csv <path>]
        [--inline-js]
        [--out <path>]
        [--open]
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from trend_data import (  # noqa: E402
    auto_bucket, bucket_index, date_bounds, month_bounds, num_buckets,
    parse_last, prior_window_for, read_sessions_in_range,
)
from chart_runtime import chartjs_script_tags  # noqa: E402
from roots import reports_directory  # noqa: E402

DEFAULT_CSV_PATH = reports_directory() / "sessions.csv"
DEFAULT_OUT_DIR = reports_directory()


def _resolve_current_window(arguments, parser):
    """Return (current_start, current_end, mode, range_label, range_filename, span_days).

    Centralizes the three-mode dispatch so main() reads cleanly.
    """
    if arguments.month:
        try:
            current_start, current_end = month_bounds(arguments.month)
        except ValueError:
            parser.error(f"--month must be YYYY-MM, got {arguments.month!r}")
        return (current_start, current_end, "month",
                arguments.month, arguments.month,
                (current_end - current_start).days + 1)
    if arguments.start:
        if not arguments.end:
            parser.error("--start requires --end")
        current_start, current_end = date_bounds(arguments.start, arguments.end)
        return (current_start, current_end, "range",
                f"{arguments.start} → {arguments.end}",
                f"{arguments.start}_{arguments.end}",
                (current_end - current_start).days + 1)
    if arguments.last:
        try:
            duration = parse_last(arguments.last)
        except ValueError as exc:
            parser.error(str(exc))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        current_start = now - duration
        current_end = now
        return (current_start, current_end, "duration",
                f"last {arguments.last}", f"last-{arguments.last}",
                max(1, duration.days))
    # Unreachable: argparse `required=True` on the mutex group catches this.
    parser.error("one of --month, --start/--end, --last is required")


def aggregate_per_bucket(rows, window_start, granularity, total_buckets):
    """Return list[float] of length total_buckets with per-bucket cost."""
    per_bucket = [0.0] * total_buckets
    for row in rows:
        index = bucket_index(row["_parsed_timestamp"], window_start, granularity)
        if 0 <= index < total_buckets:
            per_bucket[index] += row["_cost_usd_float"]
    return [round(value, 2) for value in per_bucket]


def cumulative(per_bucket):
    out = []
    running = 0.0
    for value in per_bucket:
        running += value
        out.append(round(running, 2))
    return out


def bucket_labels(current_start, prior_start, granularity, total_buckets):
    """Build x-axis labels showing both windows' calendar dates per bucket."""
    if granularity == "day":
        unit, fmt = "Day", "%a %m-%d"
        step_days = 1
    elif granularity == "week":
        unit, fmt = "Week", "%m-%d"
        step_days = 7
    else:
        unit, fmt = "Month", "%Y-%m-%d"
        step_days = 30
    labels = []
    for index in range(total_buckets):
        current_anchor = current_start + timedelta(days=index * step_days)
        prior_anchor = prior_start + timedelta(days=index * step_days)
        labels.append(
            f"{unit} {index + 1} ({current_anchor.strftime(fmt)} / "
            f"{prior_anchor.strftime(fmt)})"
        )
    return labels


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cost compare — {range_label}</title>
{chartjs_script_tag}
<style>
  html, body {{ height: 100%; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 12px; color: #222; }}
  h1 {{ margin: 0 0 4px 0; font-size: 18px; }}
  .sub {{ font-size: 12px; color: #555; margin-bottom: 4px; }}
  .meta {{ font-family: ui-monospace, "Cascadia Mono", Menlo, monospace;
          font-size: 12px; color: #555; margin-bottom: 14px; }}
  .meta span {{ display: inline-block; margin-right: 18px; }}
  .chart-wrap {{ position: relative; width: 100%; height: 72vh; min-height: 460px; }}
  canvas {{ width: 100% !important; height: 100% !important; }}
  .footnote {{ font-size: 11px; color: #888; margin-top: 12px; }}
</style>
</head>
<body>
<h1>Cost comparison — current vs prior</h1>
<div class="sub">Range: {range_label}. Bars and lines below use bucket-index (Day/Week/Month N), so paired columns represent the same wall-clock-relative slice in each window.</div>
<div class="meta">
  <span>current: {current_start} → {current_end} (${current_total:,.2f} / {current_sessions} sessions)</span>
  <span>prior:   {prior_start} → {prior_end} (${prior_total:,.2f} / {prior_sessions} sessions)</span>
</div>
<div class="chart-wrap"><canvas id="chart"></canvas></div>
<div class="footnote">
  Bars: per-bucket cost (left y-axis). Lines: cumulative cost (right y-axis).
</div>
<script>
const LABELS = {labels_json};
const CURRENT_PER_BUCKET = {current_per_bucket_json};
const CURRENT_CUMULATIVE = {current_cumulative_json};
const PRIOR_PER_BUCKET = {prior_per_bucket_json};
const PRIOR_CUMULATIVE = {prior_cumulative_json};

new Chart(document.getElementById("chart"), {{
  data: {{
    labels: LABELS,
    datasets: [
      {{ type: "bar", label: "Current — per bucket", data: CURRENT_PER_BUCKET,
         backgroundColor: "rgba(54, 162, 235, 0.85)",
         borderColor: "rgba(20, 95, 145, 1)", borderWidth: 1,
         yAxisID: "y", order: 2 }},
      {{ type: "bar", label: "Prior — per bucket", data: PRIOR_PER_BUCKET,
         backgroundColor: "rgba(150, 150, 150, 0.75)",
         borderColor: "rgba(80, 80, 80, 1)", borderWidth: 1,
         yAxisID: "y", order: 2 }},
      {{ type: "line", label: "Current — cumulative", data: CURRENT_CUMULATIVE,
         borderColor: "rgba(20, 95, 145, 1)", backgroundColor: "rgba(0,0,0,0)",
         borderWidth: 2, tension: 0.15, pointRadius: 3,
         yAxisID: "y1", order: 1 }},
      {{ type: "line", label: "Prior — cumulative", data: PRIOR_CUMULATIVE,
         borderColor: "rgba(80, 80, 80, 1)", backgroundColor: "rgba(0,0,0,0)",
         borderWidth: 2, borderDash: [6, 4], tension: 0.15, pointRadius: 3,
         yAxisID: "y1", order: 1 }},
    ],
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    interaction: {{ mode: "index", intersect: false }},
    scales: {{
      x: {{ stacked: false, type: "category" }},
      y:  {{ beginAtZero: true, position: "left",
            title: {{ display: true, text: "Per-bucket cost ($)" }} }},
      y1: {{ beginAtZero: true, position: "right",
            grid: {{ drawOnChartArea: false }},
            title: {{ display: true, text: "Cumulative cost ($)" }} }},
    }},
    plugins: {{
      tooltip: {{
        callbacks: {{
          label: (item) => `${{item.dataset.label}}: $${{item.parsed.y.toFixed(2)}}`,
        }},
      }},
    }},
  }},
}});
</script>
</body>
</html>
"""


def render_html(*, range_label, current_start, current_end,
                prior_start, prior_end, current_total, prior_total,
                current_sessions, prior_sessions,
                labels, current_per_bucket, current_cumulative_data,
                prior_per_bucket, prior_cumulative_data, inline):
    chartjs_script_tag, _ = chartjs_script_tags(inline=inline,
                                                want_time_adapter=False)
    # range_label comes from the CLI; escape it for the HTML text context.
    return HTML_TEMPLATE.format(
        chartjs_script_tag=chartjs_script_tag,
        range_label=html.escape(range_label),
        current_start=current_start.isoformat(),
        current_end=current_end.isoformat(),
        prior_start=prior_start.isoformat(),
        prior_end=prior_end.isoformat(),
        current_total=current_total,
        prior_total=prior_total,
        current_sessions=current_sessions,
        prior_sessions=prior_sessions,
        labels_json=json.dumps(labels).replace("</", "<\\/"),
        current_per_bucket_json=json.dumps(current_per_bucket).replace("</", "<\\/"),
        current_cumulative_json=json.dumps(current_cumulative_data).replace("</", "<\\/"),
        prior_per_bucket_json=json.dumps(prior_per_bucket).replace("</", "<\\/"),
        prior_cumulative_json=json.dumps(prior_cumulative_data).replace("</", "<\\/"),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Render current vs prior same-length window as an overlay chart."
    )
    range_group = parser.add_mutually_exclusive_group(required=True)
    range_group.add_argument("--month", help="YYYY-MM")
    range_group.add_argument("--start", help="YYYY-MM-DD start (requires --end)")
    range_group.add_argument("--last", help="<digits>(h|d), e.g. 168h or 7d")
    parser.add_argument("--end", help="YYYY-MM-DD end (paired with --start)")
    parser.add_argument("--bucket", choices=("day", "week", "month"), default=None)
    parser.add_argument("--csv", default=str(DEFAULT_CSV_PATH))
    parser.add_argument("--inline-js", action="store_true")
    parser.add_argument("--out", default=None)
    parser.add_argument("--open", dest="open_browser", action="store_true")
    arguments = parser.parse_args()

    if arguments.end and not arguments.start:
        parser.error("--end requires --start")

    (current_start, current_end, mode,
     range_label, range_filename, span_days) = _resolve_current_window(arguments, parser)
    prior_start, prior_end = prior_window_for(current_start, current_end, mode=mode)
    # In month mode the prior window can be a different length (Feb 28d vs Jan 31d);
    # bucket count needs to cover the longer side so prior overflow data isn't dropped.
    prior_span_days = (prior_end - prior_start).days + 1
    chart_span_days = max(span_days, prior_span_days)
    granularity = arguments.bucket or auto_bucket(chart_span_days)

    print(f"Current window: {current_start.isoformat()} .. {current_end.isoformat()}",
          file=sys.stderr)
    print(f"Prior window:   {prior_start.isoformat()} .. {prior_end.isoformat()}",
          file=sys.stderr)
    print(f"Bucket: {granularity} (span={span_days} days, mode={mode})",
          file=sys.stderr)

    csv_path = Path(arguments.csv)
    if not csv_path.is_file():
        sys.exit(f"error: sessions.csv not found at {csv_path}. "
                 f"Run analyze-month.py first, or pass --csv <path>.")

    current_rows, _ = read_sessions_in_range(csv_path, current_start, current_end)
    prior_rows, _ = read_sessions_in_range(csv_path, prior_start, prior_end)
    print(f"Current rows: {len(current_rows)}  Prior rows: {len(prior_rows)}",
          file=sys.stderr)

    if not current_rows and not prior_rows:
        sys.exit("error: no sessions in either window. Check --csv path and range.")

    total_buckets = num_buckets(chart_span_days, granularity)
    current_per_bucket = aggregate_per_bucket(current_rows, current_start, granularity, total_buckets)
    prior_per_bucket = aggregate_per_bucket(prior_rows, prior_start, granularity, total_buckets)
    current_cumulative_data = cumulative(current_per_bucket)
    prior_cumulative_data = cumulative(prior_per_bucket)
    labels = bucket_labels(current_start, prior_start, granularity, total_buckets)

    html_text = render_html(
        range_label=range_label,
        current_start=current_start, current_end=current_end,
        prior_start=prior_start, prior_end=prior_end,
        current_total=round(sum(current_per_bucket), 2),
        prior_total=round(sum(prior_per_bucket), 2),
        current_sessions=len(current_rows),
        prior_sessions=len(prior_rows),
        labels=labels,
        current_per_bucket=current_per_bucket,
        current_cumulative_data=current_cumulative_data,
        prior_per_bucket=prior_per_bucket,
        prior_cumulative_data=prior_cumulative_data,
        inline=arguments.inline_js,
    )

    if arguments.out:
        output_path = Path(arguments.out)
    else:
        output_path = DEFAULT_OUT_DIR / f"compare-{range_filename}.html"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    print(f"Wrote {output_path}", file=sys.stderr)

    if arguments.open_browser:
        webbrowser.open(output_path.resolve().as_uri())


if __name__ == "__main__":
    main()
