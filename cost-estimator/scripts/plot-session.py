"""Render one Claude Code session's cost trajectory as an HTML chart.

Reads a single parent session JSONL, prices each turn via the shared
pricing module, and emits a self-contained-ish HTML page with a
Chart.js mixed bar + line chart: per-turn cost (bars, left y-axis)
and cumulative cost (line, right y-axis). Hover tooltips show turn
metadata (model, top tools, tokens, timestamp).

Subagent JSONL files (under <session-id>/subagents/) are summarized
in the page caption but not plotted on the timeline — overlay
sub-trajectories are deferred to a future Phase 2.

Usage:
    python plot-session.py <session-id-or-jsonl-path>
        [--projects <root> ...]    # default: ~/.claude/projects
        [--x {turn,time}]           # default: turn
        [--inline-js]               # embed Chart.js into the HTML
        [--out <path>]              # default: <skill-root>/reports/session-<id-prefix>.html
        [--open]                    # open the resulting HTML in default browser
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pricing import iter_assistant_turns  # noqa: E402


DEFAULT_PROJECTS_ROOT = Path.home() / ".claude" / "projects"


def resolve_session(argument, project_roots):
    """Return (parent_jsonl_path, session_id) for the user's argument.

    If `argument` is an existing file path ending in .jsonl, use it.
    Otherwise treat it as a session ID (or unique prefix) and search
    each project root for `<root>/<slug>/<id>.jsonl`. Error if 0 or
    >1 matches.
    """
    candidate_path = Path(argument)
    if candidate_path.is_file() and candidate_path.suffix == ".jsonl":
        return candidate_path, candidate_path.stem

    matches = []
    for root in project_roots:
        if not root.exists():
            continue
        for slug_directory in root.iterdir():
            if not slug_directory.is_dir():
                continue
            for entry in slug_directory.iterdir():
                if (entry.is_file() and entry.suffix == ".jsonl"
                        and entry.stem.startswith(argument)):
                    matches.append(entry)
    if not matches:
        sys.exit(f"error: no session JSONL matched id/prefix '{argument}' "
                 f"in roots: {[str(root) for root in project_roots]}")
    if len(matches) > 1:
        sys.exit(f"error: ambiguous id/prefix '{argument}' matched "
                 f"{len(matches)} files:\n  " + "\n  ".join(str(match) for match in matches))
    return matches[0], matches[0].stem


def collect_subagent_summary(parent_jsonl_path):
    """Return (count, aggregate_cost_usd) for sibling subagent JSONLs.

    Subagent files live at <parent-dir>/<session-id>/subagents/agent-*.jsonl.
    The parent JSONL itself sits at <parent-dir>/<session-id>.jsonl.
    """
    session_directory = parent_jsonl_path.parent / parent_jsonl_path.stem
    subagent_directory = session_directory / "subagents"
    if not subagent_directory.is_dir():
        return 0, 0.0
    count = 0
    total_cost = 0.0
    for subagent_jsonl in subagent_directory.glob("agent-*.jsonl"):
        count += 1
        for record in iter_assistant_turns(subagent_jsonl):
            total_cost += record["cost_usd"]
    return count, total_cost


def render_html(turns, subagent_count, subagent_cost,
                session_id, x_axis_mode, chartjs_inline_bytes):
    """Stub: returns None for now; HTML rendering added in Task 5."""
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Render one session's cost trajectory as an HTML chart."
    )
    parser.add_argument("session", help="Session UUID, prefix, or full JSONL path")
    parser.add_argument("--projects", action="append", default=None,
                        help="Projects root directory (default: ~/.claude/projects). "
                             "Repeat to search multiple roots.")
    parser.add_argument("--x", choices=("turn", "time"), default="turn",
                        help="X-axis mode (default: turn number)")
    parser.add_argument("--inline-js", action="store_true",
                        help="Embed Chart.js into the HTML rather than CDN-load")
    parser.add_argument("--out", default=None,
                        help="Output HTML path (default: <skill-root>/reports/session-<prefix>.html)")
    parser.add_argument("--open", dest="open_browser", action="store_true",
                        help="Open the resulting HTML in the default browser")
    arguments = parser.parse_args()

    project_roots = [Path(root) for root in (arguments.projects or [str(DEFAULT_PROJECTS_ROOT)])]
    parent_jsonl, session_id = resolve_session(arguments.session, project_roots)
    print(f"Resolved session: {session_id}", file=sys.stderr)
    print(f"  parent jsonl: {parent_jsonl}", file=sys.stderr)

    turns = list(iter_assistant_turns(parent_jsonl))
    cumulative = 0.0
    for record in turns:
        cumulative += record["cost_usd"]
        record["cumulative_cost"] = round(cumulative, 6)
    total_cost = cumulative
    print(f"  parent turns: {len(turns)}  parent cost: ${total_cost:.4f}",
          file=sys.stderr)

    subagent_count, subagent_cost = collect_subagent_summary(parent_jsonl)
    print(f"  subagents: {subagent_count} files  ${subagent_cost:.4f}",
          file=sys.stderr)

    # HTML rendering is added in Task 5. For now, dump a JSON preview.
    preview = {
        "session_id": session_id,
        "parent_total": round(total_cost, 4),
        "subagent_count": subagent_count,
        "subagent_cost": round(subagent_cost, 4),
        "first_turn": turns[0] if turns else None,
        "last_turn": turns[-1] if turns else None,
    }
    print(json.dumps(preview, indent=2, default=str))


if __name__ == "__main__":
    main()
