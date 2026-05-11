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
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from trend_data import (  # noqa: E402
    auto_bucket, date_bounds, month_bounds,
    parse_last, prior_window_for, read_sessions_in_range,
)
# Task 5 will re-add `bucket_index` and `num_buckets` to this import line
# once they're defined in trend_data.py.

DEFAULT_CSV_PATH = Path(__file__).resolve().parent.parent / "reports" / "sessions.csv"
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "reports"


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
    granularity = arguments.bucket or auto_bucket(span_days)

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

    # Rendering follows in Task 5.
    print("(skeleton — chart rendering lands in Task 5)", file=sys.stderr)


if __name__ == "__main__":
    main()
