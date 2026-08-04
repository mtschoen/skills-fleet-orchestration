"""Read sessions.csv from analyze-month.py and surface usage patterns.

Reports:
    - subagent vs parent-only cost (lets us reconcile against ccusage)
    - measured parent, subagent, and slash-command active time
    - tool-call totals and "skill candidates" (high-frequency repeat queries)
    - first-turn input bloat ranking (MCP/skill loader overhead per session)
    - daily totals
    - top-N sessions with full tool breakdown

Usage:
    python summarize.py [--csv <path>] [--paid <usd>]
        [--commands-csv <path>] [--command /name]

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


def normalize_command(command):
    command = command.strip().split(maxsplit=1)[0] if command.strip() else ""
    if not command:
        return None
    if not command.startswith("/"):
        command = f"/{command}"
    return command.lower()


def format_duration(seconds):
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {remaining_seconds:02d}s"
    return f"{minutes}m {remaining_seconds:02d}s"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv",
                        default=str(reports_directory() / "sessions.csv"),
                        help="sessions.csv path produced by analyze-month.py "
                             "(default: ~/.claude/cost-estimator/reports/sessions.csv)")
    parser.add_argument("--paid", type=float, default=None,
                        help="Actual USD paid for the period (Max plan + extras). "
                             "When provided, reports leverage and prorated columns.")
    parser.add_argument("--commands-csv", default=None,
                        help="commands.csv path produced by analyze-month.py "
                             "(default: alongside --csv)")
    parser.add_argument("--command", default=None,
                        help="Show session detail for one slash command, such as /wrap")
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
            for key in ("active_time_seconds", "subagent_time_seconds"):
                row[key] = float(row.get(key) or 0)
            row["timed_turns"] = int(row.get("timed_turns") or 0)
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
        subagent_percent = (
            bucket["subagent"] / bucket["total"] * 100
            if bucket["total"] > 0 else 0.0
        )
        grand_total += bucket["total"]
        grand_parent += parent_only
        grand_sub += bucket["subagent"]
        print(f"  {label:9}  total ${bucket['total']:>9.2f}  "
              f"parent-only ${parent_only:>9.2f}  "
              f"subagent ${bucket['subagent']:>8.2f} "
              f"({subagent_percent:5.1f}%)")
    print(f"  {'TOTAL':9}  total ${grand_total:>9.2f}  "
          f"parent-only ${grand_parent:>9.2f}  subagent ${grand_sub:>8.2f}")

    parent_active_seconds = sum(row["active_time_seconds"] for row in rows)
    subagent_active_seconds = sum(row["subagent_time_seconds"] for row in rows)
    timed_turns = sum(row["timed_turns"] for row in rows)
    print("\n=== ACTIVE TIME (turn_duration wall clock) ===")
    print(f"  Parent active time (user wait): {format_duration(parent_active_seconds)}")
    print(f"  Timed parent turns: {timed_turns:,}")
    print("  Subagent processing time (reported separately; may overlap): "
          f"{format_duration(subagent_active_seconds)}")

    commands_path = (
        Path(arguments.commands_csv)
        if arguments.commands_csv
        else path.with_name("commands.csv")
    )
    command_rows = []
    if commands_path.is_file():
        with open(commands_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for command_row in reader:
                command_row["invocations"] = int(command_row["invocations"] or 0)
                command_row["active_seconds"] = float(command_row["active_seconds"] or 0)
                command_rows.append(command_row)

    print("\n=== SLASH COMMAND TIME ===")
    command_totals = defaultdict(lambda: {"invocations": 0, "seconds": 0.0,
                                          "sessions": set()})
    for command_row in command_rows:
        bucket = command_totals[command_row["command"]]
        bucket["invocations"] += command_row["invocations"]
        bucket["seconds"] += command_row["active_seconds"]
        bucket["sessions"].add((command_row["label"], command_row["session_id"]))
    if not command_totals:
        print(f"  No timed slash commands found in {commands_path}.")
    for command, bucket in sorted(
        command_totals.items(), key=lambda item: -item[1]["seconds"],
    ):
        print(f"  {command:30} {format_duration(bucket['seconds']):>12}  "
              f"{bucket['invocations']} timed invocations  "
              f"{len(bucket['sessions'])} sessions")

    requested_command = normalize_command(arguments.command) if arguments.command else None
    if requested_command:
        print(f"\n=== COMMAND DETAIL: {requested_command} ===")
        matching_rows = [
            command_row for command_row in command_rows
            if command_row["command"].lower() == requested_command
        ]
        if not matching_rows:
            print("  No timed invocations found.")
        for command_row in sorted(
            matching_rows, key=lambda item: -item["active_seconds"],
        ):
            print(f"  {command_row['session_date']}  "
                  f"{format_duration(command_row['active_seconds']):>12}  "
                  f"{command_row['invocations']} timed invocations  "
                  f"id={command_row['session_id'][:8]}  {command_row['label']}")

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
