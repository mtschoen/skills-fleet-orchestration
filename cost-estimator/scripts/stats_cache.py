"""Reconcile the cost-estimator's transcript walk against Claude Code's
per-machine /stats aggregate (stats-cache.json).

Why this exists: the retrospective analyzer prices *surviving* session
transcripts. Under the old 30-day retention, heavy old days were garbage-
collected before they could be priced, so a month report for a pre-retention
window silently undercounts. stats-cache.json's `dailyModelTokens` is the only
surviving fossil record of those days' input+output volume (it carries no
cache and no dollars -- costUSD is always 0 -- so we still price ourselves).

This module:
  - reads stats-cache.json (sibling of the projects/ root, via roots.py),
  - extracts per-day input+output from `dailyModelTokens`,
  - walks surviving transcripts for per-day input+output (deduped by
    message.id, parents + subagents),
  - classifies each day as match / partial / cleared, and
  - reports a coverage % so a report flags when its dollar total is a FLOOR.

CLI prints the full per-day reconciliation + the stats file's own modelUsage
inventory. analyze-month.py imports `coverage_for_roots` + `format_warning`
to emit a one-line guardrail in the normal report flow.

Caveats:
  - per-machine, not account-wide (one stats-cache.json per root);
  - daily granularity only; `dailyModelTokens` excludes cache entirely;
  - the file is stale until `/stats` is opened (lastComputedDate);
  - the headline /stats token count is NOT deduped (~3.2x hot) -- we never
    use it for spend math, only `dailyModelTokens` for coverage comparison.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from roots import (  # noqa: E402  -- after sys.path manipulation
    _resolve_roots,
    date_bounds,
    month_bounds,
    stats_file_for,
)

# A day counts as cache-CLEARED when /stats recorded a substantial in+out
# volume but the surviving transcripts hold almost none of it.
CLEARED_FLOOR = 50_000      # ignore tiny days; only flag days that mattered
CLEARED_RATIO = 0.10        # transcripts < 10% of /stats => cleared
# A day MATCHES when the two sources agree within a tolerance.
MATCH_FLOOR = 5_000         # absolute slack for small days
MATCH_RATIO = 0.25          # or 25% relative slack
# Coverage below this fraction triggers the report-flow warning.
WARN_THRESHOLD = 0.90


def load_stats(path):
    """Parse a stats-cache.json. Returns the dict, or None if absent."""
    path = Path(path)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def stats_daily_in_out(stats):
    """{date: input+output} from dailyModelTokens (summed across models)."""
    daily = {}
    for record in (stats or {}).get("dailyModelTokens", []):
        daily[record["date"]] = sum(record.get("tokensByModel", {}).values())
    return daily


def daily_in_out_of_file(path, dedupe=True):
    """{date: input+output} for one transcript JSONL.

    dedupe=True  -> count each message.id once (the honest token volume,
                    matches the analyzer's pricing walk).
    dedupe=False -> count every assistant line (RAW). This is what /stats
                    dailyModelTokens does, so coverage reconciliation uses
                    raw mode for an apples-to-apples comparison (verified
                    2026-05-29: raw transcript in+out == /stats per-day to
                    the token on intact days; deduped runs ~3x low).
    """
    seen = set()
    daily = defaultdict(int)
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("type") != "assistant":
                continue
            message = entry.get("message") or {}
            message_id = message.get("id")
            if dedupe:
                if not message_id or message_id in seen:
                    continue
                seen.add(message_id)
            usage = message.get("usage") or {}
            in_out = (usage.get("input_tokens", 0) or 0) + \
                     (usage.get("output_tokens", 0) or 0)
            timestamp = entry.get("timestamp")
            if timestamp:
                daily[timestamp[:10]] += in_out
    return dict(daily)


def walk_transcripts_daily_in_out(root, dedupe=True):
    """Merge daily_in_out across all parent + subagent transcripts under root.

    Pass dedupe=False for /stats coverage reconciliation (raw mode).
    """
    root = Path(root)
    paths = glob.glob(str(root / "*" / "*.jsonl"))
    paths += glob.glob(str(root / "*" / "*" / "subagents" / "*.jsonl"))
    merged = defaultdict(int)
    for path in paths:
        try:
            per_file = daily_in_out_of_file(path, dedupe=dedupe)
        except OSError:
            continue
        for day, value in per_file.items():
            merged[day] += value
    return dict(merged)


def classify_days(stats_daily, transcript_daily, *,
                  cleared_floor=CLEARED_FLOOR, cleared_ratio=CLEARED_RATIO,
                  match_floor=MATCH_FLOOR, match_ratio=MATCH_RATIO):
    """Label each /stats day as 'cleared', 'match', or 'partial'."""
    status = {}
    for day, stats_value in stats_daily.items():
        transcript_value = transcript_daily.get(day, 0)
        if stats_value > cleared_floor and \
                transcript_value < cleared_ratio * stats_value:
            status[day] = "cleared"
        elif abs(stats_value - transcript_value) < \
                max(match_floor, match_ratio * stats_value):
            status[day] = "match"
        else:
            status[day] = "partial"
    return status


@dataclass
class Coverage:
    """Reconciliation summary for a date range."""
    stats_total: int
    transcript_total: int
    coverage_pct: float | None  # None when there is no /stats volume to compare
    cleared_days: list
    cleared_tokens: int
    statuses: dict
    stats_by_day: dict | None = None       # /stats in+out per day, in-range
    transcript_by_day: dict | None = None   # transcript in+out per day, in-range


def _in_range(day, start, end):
    """day 'YYYY-MM-DD' within [start, end); start/end are UTC datetimes."""
    return start.date().isoformat() <= day < end.date().isoformat()


def coverage(stats_daily, transcript_daily, start, end, **classify_kwargs):
    """Compare /stats vs transcript in+out over [start, end) (end exclusive)."""
    stats_in_range = {
        day: value for day, value in stats_daily.items()
        if _in_range(day, start, end)
    }
    transcript_in_range = {
        day: value for day, value in transcript_daily.items()
        if _in_range(day, start, end)
    }
    stats_total = sum(stats_in_range.values())
    transcript_total = sum(transcript_in_range.values())
    statuses = classify_days(stats_in_range, transcript_daily, **classify_kwargs)
    cleared_days = sorted(d for d, s in statuses.items() if s == "cleared")
    cleared_tokens = sum(stats_in_range[d] for d in cleared_days)
    coverage_pct = (transcript_total / stats_total) if stats_total > 0 else None
    return Coverage(stats_total, transcript_total, coverage_pct,
                    cleared_days, cleared_tokens, statuses,
                    stats_in_range, transcript_in_range)


def coverage_for_roots(resolved_roots, start, end, **classify_kwargs):
    """Combine stats + transcripts across roots for [start, end).

    Returns (combined Coverage, per_root) where per_root is a list of
    (label, Coverage, stats_path, stats_present) tuples.
    """
    combined_stats = defaultdict(int)
    combined_transcript = defaultdict(int)
    per_root = []
    for label, root in resolved_roots:
        stats_path = stats_file_for(root)
        stats = load_stats(stats_path)
        stats_daily = stats_daily_in_out(stats) if stats else {}
        # RAW walk: /stats dailyModelTokens is non-deduped, so compare like
        # with like. Deduping here would falsely report ~30% coverage on
        # fully-intact months (the ~3.2x no-dedup factor, not real loss).
        transcript_daily = walk_transcripts_daily_in_out(root, dedupe=False)
        per_root.append((
            label,
            coverage(stats_daily, transcript_daily, start, end, **classify_kwargs),
            stats_path,
            stats is not None,
        ))
        for day, value in stats_daily.items():
            combined_stats[day] += value
        for day, value in transcript_daily.items():
            combined_transcript[day] += value
    combined = coverage(dict(combined_stats), dict(combined_transcript),
                        start, end, **classify_kwargs)
    return combined, per_root


def format_warning(cov, *, threshold=WARN_THRESHOLD):
    """One-line guardrail for the report flow, or None when coverage is fine."""
    if cov.coverage_pct is None or cov.coverage_pct >= threshold:
        return None
    message = (
        f"coverage warning: surviving transcripts hold "
        f"{100 * cov.coverage_pct:.0f}% of the /stats in+out aggregate for "
        f"this range ({cov.transcript_total:,} of {cov.stats_total:,} tokens). "
        f"{len(cov.cleared_days)} day(s) appear cache-cleared (transcripts "
        f"GC'd under old retention) -- dollar totals are a FLOOR for this range."
    )
    if cov.cleared_days:
        shown = ", ".join(cov.cleared_days[:10])
        if len(cov.cleared_days) > 10:
            shown += f", +{len(cov.cleared_days) - 10} more"
        message += f" Cleared days: {shown}"
    return message


def _print_model_usage(stats, label):
    usage = (stats or {}).get("modelUsage") or {}
    if not usage:
        return
    print(f"\n[{label}] modelUsage inventory (cumulative, per-machine):")
    header = f"  {'model':<32} {'in':>13} {'out':>13} {'cache_read':>15} {'cache_create':>14}"
    print(header)
    for model, info in sorted(usage.items(),
                              key=lambda kv: -(kv[1].get("inputTokens", 0)
                                               + kv[1].get("outputTokens", 0))):
        print(f"  {model:<32} {info.get('inputTokens', 0):>13,} "
              f"{info.get('outputTokens', 0):>13,} "
              f"{info.get('cacheReadInputTokens', 0):>15,} "
              f"{info.get('cacheCreationInputTokens', 0):>14,}")


def _print_day_table(cov, label):
    if not cov.statuses:
        print(f"\n[{label}] no /stats days in range.")
        return
    print(f"\n[{label}] per-day reconciliation (range only):")
    print(f"  {'date':<12} {'/stats in+out':>15} {'transcripts':>15} {'status':>10}")
    print("  " + "-" * 56)
    stats_by_day = cov.stats_by_day or {}
    transcript_by_day = cov.transcript_by_day or {}
    for day in sorted(cov.statuses):
        print(f"  {day:<12} {stats_by_day.get(day, 0):>15,} "
              f"{transcript_by_day.get(day, 0):>15,} {cov.statuses[day]:>10}")


def main():
    parser = argparse.ArgumentParser(
        description="Reconcile transcripts against /stats stats-cache.json.")
    parser.add_argument("roots", nargs="*",
                        help="One or more .claude/projects directories")
    range_group = parser.add_mutually_exclusive_group(required=True)
    range_group.add_argument("--month", help="YYYY-MM (e.g. 2026-04)")
    range_group.add_argument("--start",
                             help="YYYY-MM-DD inclusive start (paired with --end)")
    parser.add_argument("--end", help="YYYY-MM-DD inclusive end (with --start)")
    parser.add_argument("--label", action="append",
                        help="Label paired with each root (repeatable)")
    parser.add_argument("--threshold", type=float, default=WARN_THRESHOLD,
                        help="Coverage fraction below which to warn (default 0.90)")
    arguments = parser.parse_args()

    if arguments.month and arguments.end:
        parser.error("--end requires --start, not --month")
    if arguments.month:
        try:
            start, end = month_bounds(arguments.month)
        except ValueError:
            parser.error(f"--month must be YYYY-MM, got {arguments.month!r}")
        range_label = arguments.month
    else:
        if not arguments.end:
            parser.error("--start requires --end")
        start, end = date_bounds(arguments.start, arguments.end)
        range_label = f"{arguments.start}..{arguments.end}"

    resolved_roots = _resolve_roots(
        cli_roots=arguments.roots,
        cli_labels=arguments.label,
        env_value=os.environ.get("CLAUDE_COST_ROOTS"),
    )

    combined, per_root = coverage_for_roots(resolved_roots, start, end)

    print("=" * 72)
    print(f"stats-cache reconciliation for {range_label}")
    print("=" * 72)
    for label, cov, stats_path, present in per_root:
        marker = "" if present else "  (stats-cache.json NOT FOUND)"
        print(f"\n--- {label}: {stats_path}{marker} ---")
        if present:
            _print_model_usage(load_stats(stats_path), label)
        _print_day_table(cov, label)
        if cov.coverage_pct is not None:
            print(f"  coverage: {100 * cov.coverage_pct:.1f}%  "
                  f"({cov.transcript_total:,} transcript / "
                  f"{cov.stats_total:,} /stats in+out)")
            print(f"  cleared days: {len(cov.cleared_days)}  "
                  f"({cov.cleared_tokens:,} in+out tokens with no surviving "
                  f"transcript)")

    print("\n" + "=" * 72)
    print("COMBINED")
    print("=" * 72)
    if combined.coverage_pct is None:
        print("  no /stats in+out volume recorded for this range "
              "(nothing to reconcile).")
    else:
        print(f"  coverage: {100 * combined.coverage_pct:.1f}%  "
              f"({combined.transcript_total:,} transcript / "
              f"{combined.stats_total:,} /stats in+out)")
        warning = format_warning(combined, threshold=arguments.threshold)
        if warning:
            print(f"\n  {warning}")
        else:
            print("  coverage is healthy for this range; no undercount warning.")


if __name__ == "__main__":
    main()
