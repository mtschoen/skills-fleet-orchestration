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
        [--out <path>]              # default: ~/.agents/cost-estimator/reports/session-<id-prefix>.html
        [--open]                    # open the resulting HTML in default browser
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import webbrowser
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pricing import iter_assistant_turns, model_family  # noqa: E402
from chart_runtime import chartjs_script_tags  # noqa: E402
from roots import reports_directory  # noqa: E402


DEFAULT_PROJECTS_ROOT = Path.home() / ".claude" / "projects"

# Filled via str.format(). Literal `{` / `}` in the rendered HTML/CSS/JS
# must be doubled (`{{` / `}}`); single-brace `{name}` is a format
# placeholder.
HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Session {session_id_prefix} — cost trajectory</title>
{chartjs_script_tag}
{time_adapter_script_tag}
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
<h1>Session {session_id}</h1>
<div class="meta">
  <span>Date: {first_date}</span>
  <span>Total (parent): ${total_cost:.4f}</span>
  <span>Turns: {turn_count}</span>
  <span>Models: {models_label}</span>
  <span>Subagents: {subagent_count} dispatches, ${subagent_cost:.4f} aggregate</span>
</div>
<div class="chart-wrap"><canvas id="chart"></canvas></div>
<div class="footnote">
  Subagent costs are summarized above but not plotted on the timeline.
  Per-subagent overlay curves are a planned Phase 2 enhancement.
</div>
<script>
const TURNS = {turns_json};
const X_MODE = "{x_axis_mode}";

const useTimeScale = X_MODE === "time";
const labels = useTimeScale ? TURNS.map(t => t.timestamp) : TURNS.map(t => `Turn ${{t.index}}`);
const perTurn = useTimeScale
  ? TURNS.map(t => ({{ x: t.timestamp, y: t.cost_usd }}))
  : TURNS.map(t => t.cost_usd);
const cumulative = useTimeScale
  ? TURNS.map(t => ({{ x: t.timestamp, y: t.cumulative_cost }}))
  : TURNS.map(t => t.cumulative_cost);

new Chart(document.getElementById("chart"), {{
  type: "bar",
  data: {{
    labels: labels,
    datasets: [
      {{
        type: "bar",
        label: "Per-turn cost (USD)",
        data: perTurn,
        backgroundColor: "rgba(54, 162, 235, 1)",
        borderColor: "rgba(20, 95, 145, 1)",
        borderWidth: 1,
        categoryPercentage: 1.0,
        barPercentage: 1.0,
        yAxisID: "yLeft",
      }},
      {{
        type: "line",
        label: "Cumulative cost (USD)",
        data: cumulative,
        borderColor: "rgba(220, 53, 69, 0.9)",
        backgroundColor: "rgba(220, 53, 69, 0.15)",
        tension: 0.1,
        yAxisID: "yRight",
      }},
    ],
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: "index", intersect: false }},
    scales: {{
      x: useTimeScale
        ? {{ type: "time", time: {{ tooltipFormat: "yyyy-MM-dd HH:mm:ss" }},
             title: {{ display: true, text: "Wall-clock time" }} }}
        : {{ title: {{ display: true, text: "Turn" }} }},
      yLeft:  {{ position: "left",
                title: {{ display: true, text: "Turn cost (USD)" }} }},
      yRight: {{ position: "right",
                title: {{ display: true, text: "Cumulative (USD)" }},
                grid: {{ drawOnChartArea: false }} }},
    }},
    plugins: {{
      tooltip: {{
        callbacks: {{
          afterBody: (items) => {{
            const t = TURNS[items[0].dataIndex];
            return [
              `Model: ${{t.model}}`,
              `Tools: ${{t.top_tools.join(", ") || "(none)"}}`,
              `Input: ${{t.input_tokens.toLocaleString()}}  Output: ${{t.output_tokens.toLocaleString()}}`,
              `Cache read: ${{t.cache_read_tokens.toLocaleString()}}  Cache write: ${{t.cache_write_tokens.toLocaleString()}}`,
              `Timestamp: ${{t.timestamp}}`,
            ];
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


def _models_label(turns):
    """Build a 'family:tokens' summary like 'opus:1234567,sonnet:23456'."""
    totals = Counter()
    for record in turns:
        family = model_family(record["model"]) or record["model"] or "?"
        totals[family] += (record["input_tokens"] + record["output_tokens"]
                           + record["cache_read_tokens"] + record["cache_write_tokens"])
    return ",".join(f"{family}:{total}" for family, total in totals.most_common())


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


def render_html(turns, subagent_count, subagent_cost, session_id,
                x_axis_mode, inline):
    chartjs_script_tag, time_adapter_script_tag = chartjs_script_tags(
        inline=inline,
        want_time_adapter=(x_axis_mode == "time"),
    )

    first_date = turns[0]["timestamp"][:10] if turns and turns[0]["timestamp"] else "?"
    total_cost = turns[-1]["cumulative_cost"] if turns else 0.0

    # Escape string fields rendered into HTML text context - model ids can
    # legitimately contain angle brackets (e.g. `<synthetic>`).
    return HTML_TEMPLATE.format(
        session_id=html.escape(session_id),
        session_id_prefix=html.escape(session_id[:8]),
        chartjs_script_tag=chartjs_script_tag,
        time_adapter_script_tag=time_adapter_script_tag,
        first_date=html.escape(first_date),
        total_cost=total_cost,
        turn_count=len(turns),
        models_label=html.escape(_models_label(turns)),
        subagent_count=subagent_count,
        subagent_cost=subagent_cost,
        # Escape `</` as `<\/` so a `</script>` substring inside any string
        # field (e.g. a model id like `<synthetic>`) cannot break out of the
        # surrounding <script> block. `<\/` is valid JSON per RFC 8259.
        turns_json=json.dumps(turns, default=str).replace("</", "<\\/"),
        x_axis_mode=x_axis_mode,
    )


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
                        help="Output HTML path "
                             "(default: ~/.agents/cost-estimator/reports/session-<prefix>.html)")
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

    html_text = render_html(
        turns=turns,
        subagent_count=subagent_count,
        subagent_cost=subagent_cost,
        session_id=session_id,
        x_axis_mode=arguments.x,
        inline=arguments.inline_js,
    )

    if arguments.out:
        output_path = Path(arguments.out)
    else:
        output_path = reports_directory() / f"session-{session_id[:8]}.html"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    print(f"Wrote {output_path}", file=sys.stderr)

    if arguments.open_browser:
        webbrowser.open(output_path.resolve().as_uri())


if __name__ == "__main__":
    main()
