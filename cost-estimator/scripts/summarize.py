"""Read sessions.csv from analyze-month.py and surface usage patterns.

Reports:
    - subagent vs parent-only cost (lets us reconcile against ccusage)
    - tool-call totals and "skill candidates" (high-frequency repeat queries)
    - first-turn input bloat ranking (MCP/skill loader overhead per session)
    - daily totals
    - top-N sessions with full tool breakdown

Usage:
    python summarize.py [--csv <path>] [--paid <usd>]

If --paid is supplied, reports leverage and prorated per-session costs;
otherwise omits the prorated columns.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from roots import reports_directory  # noqa: E402  -- after sys.path manipulation


def parse_tools(serialized):
    counts = Counter()
    if not serialized:
        return counts
    for chunk in serialized.split(","):
        if ":" not in chunk:
            continue
        name, value = chunk.rsplit(":", 1)
        try:
            counts[name] = int(value)
        except ValueError:
            continue
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv",
                        default=str(reports_directory() / "sessions.csv"),
                        help="sessions.csv path produced by analyze-month.py "
                             "(default: ~/.claude/cost-estimator/reports/sessions.csv)")
    parser.add_argument("--paid", type=float, default=None,
                        help="Actual USD paid for the period (Max plan + extras). "
                             "When provided, reports leverage and prorated columns.")
    arguments = parser.parse_args()

    path = Path(arguments.csv)
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            for key in ("cost_usd", "subagent_cost", "cache_hit_pct"):
                row[key] = float(row[key] or 0)
            for key in ("input_tokens", "output_tokens", "cache_read_tokens",
                        "cache_write_tokens", "first_turn_input_tokens",
                        "assistant_turns", "user_turns", "subagent_count"):
                row[key] = int(row[key] or 0)
            rows.append(row)

    by_label = defaultdict(lambda: {"total": 0.0, "subagent": 0.0, "sessions": 0,
                                    "input": 0, "output": 0, "cr": 0, "cw": 0})
    for row in rows:
        bucket = by_label[row["label"]]
        bucket["total"] += row["cost_usd"]
        bucket["subagent"] += row["subagent_cost"]
        bucket["sessions"] += 1
        bucket["input"] += row["input_tokens"]
        bucket["output"] += row["output_tokens"]
        bucket["cr"] += row["cache_read_tokens"]
        bucket["cw"] += row["cache_write_tokens"]

    print("=== COST RECONCILIATION (parent vs subagent) ===")
    grand_total = grand_parent = grand_sub = 0.0
    for label, bucket in by_label.items():
        parent_only = bucket["total"] - bucket["subagent"]
        grand_total += bucket["total"]
        grand_parent += parent_only
        grand_sub += bucket["subagent"]
        print(f"  {label:9}  total ${bucket['total']:>9.2f}  "
              f"parent-only ${parent_only:>9.2f}  "
              f"subagent ${bucket['subagent']:>8.2f} "
              f"({bucket['subagent']/bucket['total']*100:5.1f}%)")
    print(f"  {'TOTAL':9}  total ${grand_total:>9.2f}  "
          f"parent-only ${grand_parent:>9.2f}  subagent ${grand_sub:>8.2f}")

    # Tool-call aggregation
    tool_totals = Counter()
    tool_sessions = Counter()
    for row in rows:
        tools = parse_tools(row["top_tools"])
        for name, count in tools.items():
            tool_totals[name] += count
            tool_sessions[name] += 1

    print("\n=== TOP TOOL CALLS (all sessions, top-5 per session aggregated) ===")
    for name, count in tool_totals.most_common(20):
        coverage = tool_sessions[name] / len(rows) * 100
        print(f"  {name:40}  {count:>6} calls   in {tool_sessions[name]:>3}/{len(rows)} sessions ({coverage:4.1f}%)")

    # First-turn input bloat (MCP/skill loader proxy)
    print("\n=== FIRST-TURN INPUT TOKENS (system+tool-schema bloat per session) ===")
    sized = [(row["first_turn_input_tokens"], row) for row in rows
             if row["first_turn_input_tokens"] > 0]
    sized.sort(key=lambda item: -item[0])
    bloat_total = sum(item[0] for item in sized)
    print(f"  Sum of first-turn input tokens across all sessions: {bloat_total:,}")
    print(f"  Mean: {bloat_total // len(sized) if sized else 0:,}    "
          f"Median: {sized[len(sized)//2][0] if sized else 0:,}")
    print("  Top 10 (largest opening payload):")
    for tokens, row in sized[:10]:
        print(f"    {tokens:>8,} tokens   ${row['cost_usd']:>7.2f}  "
              f"hit={row['cache_hit_pct']:>5.1f}%  id={row['session_id'][:8]}  "
              f"{row['label']}")

    discount_factor = None
    if arguments.paid is not None and grand_total > 0:
        leverage = grand_total / arguments.paid
        discount_factor = arguments.paid / grand_total
        print("\n=== SUBSCRIPTION LEVERAGE ===")
        print(f"  Raw token cost (analyzer): ${grand_total:,.2f}")
        print(f"  Actually paid: ${arguments.paid:,.2f}")
        print(f"  Leverage: {leverage:.1f}x")
        print(f"  Implied discount factor: {discount_factor:.4f} "
              f"(prorated cost = raw × {discount_factor:.4f})")

    print("\n=== TOP 20 SESSIONS ===")
    rows.sort(key=lambda r: -r["cost_usd"])
    if discount_factor is not None:
        print(f"  {'Raw $':>9}  {'Prorated $':>9}  {'Date':>10}  {'Hit':>5}  "
              f"{'Sub':>4}  {'Turns':>5}  {'1stTurn':>9}  Top-5 tools")
        for row in rows[:20]:
            prorated = row["cost_usd"] * discount_factor
            first_turn_kib = row["first_turn_input_tokens"] // 1024
            print(f"  ${row['cost_usd']:>7.2f}  ${prorated:>7.2f}  {row['session_date']:>10}  "
                  f"{row['cache_hit_pct']:>4.1f}%  {row['subagent_count']:>4}  "
                  f"{row['assistant_turns']:>5}  {first_turn_kib:>7}KT  "
                  f"{row['top_tools'][:80]}")
    else:
        print(f"  {'Raw $':>9}  {'Date':>10}  {'Hit':>5}  "
              f"{'Sub':>4}  {'Turns':>5}  {'1stTurn':>9}  Top-5 tools")
        for row in rows[:20]:
            first_turn_kib = row["first_turn_input_tokens"] // 1024
            print(f"  ${row['cost_usd']:>7.2f}  {row['session_date']:>10}  "
                  f"{row['cache_hit_pct']:>4.1f}%  {row['subagent_count']:>4}  "
                  f"{row['assistant_turns']:>5}  {first_turn_kib:>7}KT  "
                  f"{row['top_tools'][:80]}")

    # Skill/memory candidates: tools that fired in many sessions and many calls
    print("\n=== SKILL/MEMORY CANDIDATES (high-fanout repeat patterns) ===")
    print("  Tools called in >50% of sessions and >1000 total calls:")
    threshold_sessions = len(rows) * 0.5
    for name, count in tool_totals.most_common():
        if tool_sessions[name] >= threshold_sessions and count >= 1000:
            avg_per_session = count / tool_sessions[name]
            print(f"    {name:40}  {count:>6} calls   "
                  f"in {tool_sessions[name]:>3} sessions   "
                  f"avg {avg_per_session:>5.1f}/session")

    # Daily breakdown
    print("\n=== DAILY TOTALS ===")
    by_day = defaultdict(lambda: {"sessions": 0, "cost": 0.0, "subagent": 0.0,
                                  "subagents": 0, "machines": set()})
    for row in rows:
        day = row["session_date"]
        by_day[day]["sessions"] += 1
        by_day[day]["cost"] += row["cost_usd"]
        by_day[day]["subagent"] += row["subagent_cost"]
        by_day[day]["subagents"] += row["subagent_count"]
        by_day[day]["machines"].add(row["label"])
    if discount_factor is not None:
        print(f"  {'Date':>10}  {'Sessions':>8}  {'Raw $':>9}  {'Prorated $':>9}  "
              f"{'Subagent $':>10}  {'#Subagents':>10}  Machines")
        for day in sorted(by_day):
            bucket = by_day[day]
            prorated = bucket["cost"] * discount_factor
            machines = "+".join(sorted(bucket["machines"]))
            print(f"  {day:>10}  {bucket['sessions']:>8}  "
                  f"${bucket['cost']:>7.2f}  ${prorated:>7.2f}  "
                  f"${bucket['subagent']:>8.2f}  {bucket['subagents']:>10}  {machines}")
    else:
        print(f"  {'Date':>10}  {'Sessions':>8}  {'Raw $':>9}  "
              f"{'Subagent $':>10}  {'#Subagents':>10}  Machines")
        for day in sorted(by_day):
            bucket = by_day[day]
            machines = "+".join(sorted(bucket["machines"]))
            print(f"  {day:>10}  {bucket['sessions']:>8}  "
                  f"${bucket['cost']:>7.2f}  "
                  f"${bucket['subagent']:>8.2f}  {bucket['subagents']:>10}  {machines}")


if __name__ == "__main__":
    main()
