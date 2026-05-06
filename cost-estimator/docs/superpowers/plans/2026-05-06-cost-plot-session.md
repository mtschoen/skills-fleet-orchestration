# Cost Plot-Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `plot-session.py` script to the cost-estimator skill that renders one Claude Code session's cost trajectory as an interactive HTML chart (per-turn bars + cumulative line + hover tooltips), so the user can investigate spike sessions surfaced by `summarize.py`.

**Architecture:** Extract the canonical pricing formula from `analyze-month.py` into a new shared `pricing.py` module to remove drift risk. Build `plot-session.py` on top of it: argparse → resolve session ID/path → walk the parent JSONL via a new `iter_assistant_turns()` helper → emit an HTML page with Chart.js (CDN by default, embeddable via `--inline-js`). Subagent costs are summarized in the page caption but not plotted on the timeline — overlay sub-trajectories are deferred to a future Phase 2.

**Tech Stack:** Python 3 (stdlib + optional `orjson`, no new Python deps); Chart.js v4 from `cdn.jsdelivr.net` (or cached locally for `--inline-js`).

---

## Phase 1: Extract pricing helpers (refactor, no behavior change)

The existing `analyze-month.py` is the only place the canonical pricing formula lives. Phase 1 hoists it into `scripts/pricing.py` and wires `analyze-month.py` to import from there. Goal: byte-identical `sessions.csv` and `daily.csv` for the same input before vs. after this phase, so we know the refactor is pure.

### Task 1: Create `scripts/pricing.py` with extracted constants and helpers

**Files:**
- Create: `scripts/pricing.py`

- [x] **Step 1: Write `scripts/pricing.py`**

```python
"""Canonical pricing helpers shared across cost-estimator scripts.

Single source of truth for the per-MTok rates, cache multipliers, and
1M-context-tier doubling. Both analyze-month.py (retrospective bulk
analysis) and plot-session.py (single-session trajectory) import from
here so the formula does not drift.

Source of truth for the rate table is
~/.claude/notes/reference_anthropic_pricing.md; the values below are
duplicated for skill self-containment.
"""

from __future__ import annotations

from datetime import datetime


# Per-MTok rates (verified 2026-04 against Anthropic docs).
PRICES = {
    "opus":   (5.0, 25.0),
    "sonnet": (3.0, 15.0),
    "haiku":  (1.0, 5.0),
}
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def model_family(model_identifier):
    if not model_identifier:
        return None
    name = model_identifier.lower()
    if "opus" in name:
        return "opus"
    if "sonnet" in name:
        return "sonnet"
    if "haiku" in name:
        return "haiku"
    return None


def is_one_million_tier(model_identifier):
    return bool(model_identifier and "[1m]" in model_identifier)


def parse_timestamp(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def cost_for_turn(model_identifier, input_tokens, output_tokens,
                  cache_read_tokens, cache_write_tokens):
    family = model_family(model_identifier)
    if family is None:
        return 0.0
    input_rate, output_rate = PRICES[family]
    if is_one_million_tier(model_identifier):
        input_rate *= 2
        output_rate *= 2
    return (input_tokens * input_rate
            + output_tokens * output_rate
            + cache_read_tokens * input_rate * CACHE_READ_MULTIPLIER
            + cache_write_tokens * input_rate * CACHE_WRITE_MULTIPLIER) / 1_000_000
```

- [x] **Step 2: Smoke-test the import and a known-shape call**

Run from the repo root:
```
python -c "import sys; sys.path.insert(0, 'scripts'); from pricing import cost_for_turn, model_family, is_one_million_tier; print(model_family('claude-opus-4-7'), is_one_million_tier('claude-opus-4-7[1m]'), round(cost_for_turn('claude-opus-4-7', 1000, 100, 10000, 5000), 6))"
```
Expected output: `opus True 0.0175` (or very close — input 1000 × 5/M = 0.005; output 100 × 25/M = 0.0025; cache_read 10000 × 0.5/M = 0.005; cache_write 5000 × 6.25/M = 0.03125; sum ≈ 0.04375. Recompute: 0.005 + 0.0025 + 0.005 + 0.03125 = 0.04375. So expected `opus False 0.04375` — note the model ID in the call is the non-1m one, so the second arg printed is `False`.)

If the printed cost is not `0.04375`, the formula is wrong — debug before proceeding.

- [x] **Step 3: Commit**

```
git add scripts/pricing.py
git commit -m "pricing: extract canonical formula into shared module"
```

---

### Task 2: Refactor `analyze-month.py` to import from `pricing`

**Files:**
- Modify: `scripts/analyze-month.py` (delete extracted defs; add sys.path + import)

- [ ] **Step 1: Capture pre-refactor baseline output**

Pick a small recent date range (a single day works; any day in the last week is fine — pick one with at least a handful of sessions). Run:
```
python scripts/analyze-month.py ~/.claude/projects --start 2026-05-01 --end 2026-05-01 --label baseline --out /tmp/cost-est-baseline
```
This writes `/tmp/cost-est-baseline/sessions.csv` and `/tmp/cost-est-baseline/daily.csv`. Confirm both files have non-zero size.

- [ ] **Step 2: Edit `scripts/analyze-month.py` — remove extracted code, add the import**

Find and delete the constants block:
```python
# Per-MTok rates (verified 2026-04 against Anthropic docs;
# see ~/.claude/notes/reference_anthropic_pricing.md).
PRICES = {
    "opus":   (5.0, 25.0),
    "sonnet": (3.0, 15.0),
    "haiku":  (1.0, 5.0),
}
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10
```

Find and delete the four function definitions: `model_family`, `is_one_million_tier`, `parse_timestamp`, `cost_for_turn`.

Add this immediately after the existing `try: import orjson ...` block (so it sits with the other imports):
```python
import sys
sys.path.insert(0, str(Path(__file__).parent))
from pricing import (  # noqa: E402  -- after sys.path manipulation
    cost_for_turn,
    is_one_million_tier,
    model_family,
    parse_timestamp,
    PRICES,
    CACHE_READ_MULTIPLIER,
    CACHE_WRITE_MULTIPLIER,
)
```

(`PRICES`, `CACHE_READ_MULTIPLIER`, and `CACHE_WRITE_MULTIPLIER` are imported even though `analyze-month.py` itself doesn't reference them by name — only `cost_for_turn` does. Re-check before committing: if they aren't referenced anywhere in `analyze-month.py` after the edit, drop them from the import line. The reference function inside `pricing.py` uses them as module-level globals, not via the importer's namespace.)

- [ ] **Step 3: Re-run analyzer on the same range, into a different output dir**

```
python scripts/analyze-month.py ~/.claude/projects --start 2026-05-01 --end 2026-05-01 --label baseline --out /tmp/cost-est-refactored
```

- [ ] **Step 4: Diff the two outputs — must be byte-identical**

```
diff /tmp/cost-est-baseline/sessions.csv /tmp/cost-est-refactored/sessions.csv
diff /tmp/cost-est-baseline/daily.csv /tmp/cost-est-refactored/daily.csv
```
Expected: no output from either diff (files are identical).

If they differ: the refactor changed behavior. Inspect the diff, find the source (likely a typo in one of the four extracted functions, or a missed constant), fix `pricing.py`, re-run from Step 3.

- [ ] **Step 5: Commit**

```
git add scripts/analyze-month.py
git commit -m "analyze-month: import pricing helpers from shared module"
```

---

## Phase 2: Build plot-session.py

### Task 3: Add `iter_assistant_turns()` to `pricing.py`

**Files:**
- Modify: `scripts/pricing.py` (append new helper)

- [ ] **Step 1: Append the iterator to `scripts/pricing.py`**

Add at the bottom of `pricing.py`:
```python
try:
    import orjson as _json
    def _loads(payload):
        return _json.loads(payload)
except ImportError:
    import json as _json
    def _loads(payload):
        return _json.loads(payload)


def iter_assistant_turns(jsonl_path):
    """Yield one record per priced assistant turn in a Claude Code JSONL.

    Dedupes on `message.id` (turns recur in JSONL snapshots; naive
    iteration double-counts). Turns without a `message.id` are kept.

    Yielded record shape:
        {
          "index": 1-based turn number within this JSONL,
          "timestamp": ISO 8601 string (or "" if missing),
          "model": str (e.g. "claude-opus-4-7" or "...-7[1m]"),
          "input_tokens": int,
          "output_tokens": int,
          "cache_read_tokens": int,
          "cache_write_tokens": int,
          "cost_usd": float,
          "top_tools": list[str] of tool names from this turn's tool_use
              blocks, deduped, in first-appearance order,
        }
    """
    seen_ids = set()
    index = 0
    with open(jsonl_path, "rb") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = _loads(line)
            except Exception:
                continue
            if entry.get("type") != "assistant":
                continue
            message = entry.get("message") or {}
            if message.get("role") != "assistant":
                continue
            message_id = message.get("id")
            if message_id:
                if message_id in seen_ids:
                    continue
                seen_ids.add(message_id)

            usage = message.get("usage") or {}
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            cache_read_tokens = int(usage.get("cache_read_input_tokens") or 0)
            cache_write_tokens = int(usage.get("cache_creation_input_tokens") or 0)
            model_identifier = message.get("model") or ""

            tools_seen = []
            content = message.get("content") or []
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name") or "?"
                        if name not in tools_seen:
                            tools_seen.append(name)

            index += 1
            yield {
                "index": index,
                "timestamp": entry.get("timestamp") or "",
                "model": model_identifier,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cache_write_tokens": cache_write_tokens,
                "cost_usd": cost_for_turn(model_identifier, input_tokens,
                                          output_tokens, cache_read_tokens,
                                          cache_write_tokens),
                "top_tools": tools_seen,
            }
```

- [ ] **Step 2: Smoke-test against a real session**

Pick the highest-cost session from the `sessions.csv` you generated in Task 2 Step 3 (or re-run analyze-month.py on a wider range if that day was sparse). Note its `session_id` and the `cost_usd` value. Then run:
```
python -c "import sys; sys.path.insert(0, 'scripts'); from pricing import iter_assistant_turns; rows = list(iter_assistant_turns('<full-path-to-that-session-jsonl>')); print(f'{len(rows)} turns, ${sum(r[\"cost_usd\"] for r in rows):.4f}')"
```

Expected: the printed total should match the parent-only portion of that session's `cost_usd` (i.e. `cost_usd - subagent_cost` from sessions.csv, since `iter_assistant_turns` only walks the parent JSONL). Match within ~$0.0005 rounding tolerance.

If it diverges by more than rounding: bug. Likely culprits — wrong field name, missed dedup, off-by-one. Debug before proceeding.

- [ ] **Step 3: Commit**

```
git add scripts/pricing.py
git commit -m "pricing: add iter_assistant_turns for per-turn extraction"
```

---

### Task 4: Create `plot-session.py` CLI scaffold and turn extraction (no HTML yet)

**Files:**
- Create: `scripts/plot-session.py`

- [ ] **Step 1: Write `scripts/plot-session.py`**

```python
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
import os
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pricing import cost_for_turn, iter_assistant_turns  # noqa: E402


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
```

- [ ] **Step 2: Smoke-test the scaffold**

Pick the same high-cost session from Task 3 Step 2. Run:
```
python scripts/plot-session.py <session-id-prefix-8-chars>
```

Expected stderr:
- `Resolved session: <full-uuid>`
- `parent jsonl: <path>`
- `parent turns: <N>  parent cost: $<X.XX>`
- `subagents: <N> files  $<Y.YY>`

Expected stdout: a JSON object with `session_id`, `parent_total`, `subagent_count`, `subagent_cost`, `first_turn`, `last_turn`. Sanity-check `parent_total` matches sessions.csv `cost_usd - subagent_cost` for that session.

Test the error paths:
- Pass a bogus prefix (e.g. `"deadbeef"`) — expect a clear "no session JSONL matched" error.
- Pass a 1-char prefix that matches many — expect the "ambiguous" error listing the matches.

- [ ] **Step 3: Commit**

```
git add scripts/plot-session.py
git commit -m "plot-session: add CLI scaffold and turn extraction"
```

---

### Task 5: Add HTML rendering with Chart.js (CDN)

**Files:**
- Modify: `scripts/plot-session.py` (replace `render_html` stub; wire the call in `main`)

- [ ] **Step 1: Replace the `render_html` stub and the JSON preview block**

Add this constant near the top of the module (after the imports):
```python
HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Session {session_id_prefix} — cost trajectory</title>
{chartjs_script_tag}
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 24px; color: #222; }}
  h1 {{ margin: 0 0 8px 0; font-size: 18px; }}
  .meta {{ font-family: ui-monospace, "Cascadia Mono", Menlo, monospace;
          font-size: 12px; color: #555; margin-bottom: 16px; }}
  .meta span {{ display: inline-block; margin-right: 18px; }}
  canvas {{ max-width: 1400px; }}
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
<canvas id="chart" width="1400" height="520"></canvas>
<div class="footnote">
  Subagent costs are summarized above but not plotted on the timeline.
  Per-subagent overlay curves are a planned Phase 2 enhancement.
</div>
<script>
const TURNS = {turns_json};
const X_MODE = "{x_axis_mode}";

const labels = TURNS.map(t => X_MODE === "time" ? t.timestamp : `Turn ${{t.index}}`);
const perTurn = TURNS.map(t => t.cost_usd);
const cumulative = TURNS.map(t => t.cumulative_cost);

new Chart(document.getElementById("chart"), {{
  type: "bar",
  data: {{
    labels: labels,
    datasets: [
      {{
        type: "bar",
        label: "Per-turn cost (USD)",
        data: perTurn,
        backgroundColor: "rgba(54, 162, 235, 0.7)",
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
    interaction: {{ mode: "index", intersect: false }},
    scales: {{
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

CHARTJS_CDN_URL = "https://cdn.jsdelivr.net/npm/chart.js@4"


def _models_label(turns):
    """Build a 'family:tokens' summary like 'opus:1234567,sonnet:23456'."""
    from collections import Counter
    from pricing import model_family
    totals = Counter()
    for record in turns:
        family = model_family(record["model"]) or record["model"] or "?"
        totals[family] += (record["input_tokens"] + record["output_tokens"]
                           + record["cache_read_tokens"] + record["cache_write_tokens"])
    return ",".join(f"{family}:{total}" for family, total in totals.most_common())
```

Replace the `render_html` stub with the real implementation:
```python
def render_html(turns, subagent_count, subagent_cost, session_id,
                x_axis_mode, chartjs_inline_bytes):
    if chartjs_inline_bytes is not None:
        chartjs_script_tag = f"<script>{chartjs_inline_bytes.decode('utf-8')}</script>"
    else:
        chartjs_script_tag = f'<script src="{CHARTJS_CDN_URL}"></script>'

    first_date = turns[0]["timestamp"][:10] if turns and turns[0]["timestamp"] else "?"
    total_cost = turns[-1]["cumulative_cost"] if turns else 0.0

    return HTML_TEMPLATE.format(
        session_id=session_id,
        session_id_prefix=session_id[:8],
        chartjs_script_tag=chartjs_script_tag,
        first_date=first_date,
        total_cost=total_cost,
        turn_count=len(turns),
        models_label=_models_label(turns),
        subagent_count=subagent_count,
        subagent_cost=subagent_cost,
        turns_json=json.dumps(turns, default=str),
        x_axis_mode=x_axis_mode,
    )
```

In `main()`, replace the JSON-preview block (the `preview = {...}` and `print(json.dumps(preview, ...))` lines) with:
```python
    html_text = render_html(
        turns=turns,
        subagent_count=subagent_count,
        subagent_cost=subagent_cost,
        session_id=session_id,
        x_axis_mode=arguments.x,
        chartjs_inline_bytes=None,  # CDN by default; --inline-js wires this in Task 7
    )

    if arguments.out:
        output_path = Path(arguments.out)
    else:
        skill_root = Path(__file__).resolve().parent.parent
        reports_directory = skill_root / "reports"
        reports_directory.mkdir(parents=True, exist_ok=True)
        output_path = reports_directory / f"session-{session_id[:8]}.html"

    output_path.write_text(html_text, encoding="utf-8")
    print(f"Wrote {output_path}", file=sys.stderr)

    if arguments.open_browser:
        webbrowser.open(output_path.resolve().as_uri())
```

- [ ] **Step 2: Smoke-test the chart**

```
python scripts/plot-session.py <session-id-prefix> --open
```

Expected: a browser window opens with the chart. Verify:
- The cumulative line ends at approximately the parent total reported on stderr.
- Bar heights look reasonable (no negative bars, no huge spike that obviously doesn't match the data).
- Hovering a bar shows a tooltip with model, tools, tokens, timestamp.
- The page caption shows the subagent count + cost.

If the chart doesn't render: open the browser console — most likely a JSON serialization issue (NaN, Infinity, datetime not serialized). The `default=str` arg to `json.dumps` should cover datetimes; `cost_for_turn` should never produce NaN unless the input data is malformed.

- [ ] **Step 3: Commit**

```
git add scripts/plot-session.py
git commit -m "plot-session: render Chart.js mixed bar+line HTML page"
```

---

### Task 6: Add `--x time` toggle (wall-clock x-axis)

The Task-5 template already passes `x_axis_mode` to the JS, but Chart.js's default category axis doesn't gracefully handle the timestamp strings as a continuous time axis — turn-mode works because they're discrete labels, but time-mode needs the time scale registered. Chart.js v4 does NOT bundle the time adapter by default; we need a tiny adapter import.

**Files:**
- Modify: `scripts/plot-session.py` (add adapter script, swap labels for time data)

- [ ] **Step 1: Adjust the template to register the time scale when `x_axis_mode == "time"`**

In `HTML_TEMPLATE`, insert (right after the `{chartjs_script_tag}` line):
```html
{time_adapter_script_tag}
```

Update `render_html` to populate it:
```python
TIME_ADAPTER_CDN_URL = (
    "https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns/dist/"
    "chartjs-adapter-date-fns.bundle.min.js"
)

def render_html(turns, subagent_count, subagent_cost, session_id,
                x_axis_mode, chartjs_inline_bytes):
    if chartjs_inline_bytes is not None:
        chartjs_script_tag = f"<script>{chartjs_inline_bytes.decode('utf-8')}</script>"
    else:
        chartjs_script_tag = f'<script src="{CHARTJS_CDN_URL}"></script>'

    if x_axis_mode == "time":
        time_adapter_script_tag = f'<script src="{TIME_ADAPTER_CDN_URL}"></script>'
    else:
        time_adapter_script_tag = ""

    # ...rest unchanged...
    return HTML_TEMPLATE.format(
        # ...existing kwargs...
        time_adapter_script_tag=time_adapter_script_tag,
    )
```

In the embedded JS (inside `HTML_TEMPLATE`), update the labels and scale construction. Replace the `const labels = ...` line with:
```javascript
const useTimeScale = X_MODE === "time";
const labels = useTimeScale ? TURNS.map(t => t.timestamp) : TURNS.map(t => `Turn ${{t.index}}`);
```

And update `scales:` to add an `x` config when in time mode. Replace the existing `scales:` block with:
```javascript
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
```

When `useTimeScale` is true, Chart.js needs the data points formatted as `{x: timestamp, y: value}` rather than parallel arrays with categorical labels. Update the dataset definitions:
```javascript
const perTurn = useTimeScale
  ? TURNS.map(t => ({{ x: t.timestamp, y: t.cost_usd }}))
  : TURNS.map(t => t.cost_usd);
const cumulative = useTimeScale
  ? TURNS.map(t => ({{ x: t.timestamp, y: t.cumulative_cost }}))
  : TURNS.map(t => t.cumulative_cost);
```

(Note: `{{` and `}}` are literal `{` and `}` in the JS, escaped because the surrounding Python string uses `.format()`.)

- [ ] **Step 2: Smoke-test both axis modes**

```
python scripts/plot-session.py <session-id-prefix> --x turn --open
python scripts/plot-session.py <session-id-prefix> --x time --open
```

Verify:
- Turn mode: x-axis labels read "Turn 1", "Turn 2", etc. Same chart shape as Task 5.
- Time mode: x-axis is a continuous time axis. If the session had idle gaps (e.g. you took a break), they should show as wider spacing between bars/points.

If time mode renders blank or errors: check the browser console. Most common cause is the date-adapter not loading — verify the `<script src="...chartjs-adapter-date-fns...">` tag is present in the rendered HTML.

- [ ] **Step 3: Commit**

```
git add scripts/plot-session.py
git commit -m "plot-session: support --x time wall-clock axis"
```

---

### Task 7: Add `--inline-js` (embed Chart.js into HTML, no CDN at view time)

**Files:**
- Modify: `scripts/plot-session.py` (download + cache Chart.js, embed bytes when flag set)

- [ ] **Step 1: Add the cache + download helper, wire it into `main()`**

Near the other constants in `plot-session.py`, add:
```python
CHARTJS_INLINE_VERSION = "4.4.7"
CHARTJS_INLINE_URL = f"https://cdn.jsdelivr.net/npm/chart.js@{CHARTJS_INLINE_VERSION}/dist/chart.umd.min.js"
TIME_ADAPTER_INLINE_URL = (
    "https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/"
    "dist/chartjs-adapter-date-fns.bundle.min.js"
)


def _cached_download(url, cache_filename):
    """Return bytes of `url`, caching to ~/.cache/cost-estimator/<cache_filename>."""
    import urllib.request

    cache_directory = Path.home() / ".cache" / "cost-estimator"
    cache_directory.mkdir(parents=True, exist_ok=True)
    cache_path = cache_directory / cache_filename
    if cache_path.is_file():
        return cache_path.read_bytes()
    print(f"  fetching {url} -> {cache_path}", file=sys.stderr)
    with urllib.request.urlopen(url) as response:
        payload = response.read()
    cache_path.write_bytes(payload)
    return payload
```

Update the `chartjs_inline_bytes` argument plumbing and add a parallel `time_adapter_inline_bytes` argument. In `render_html`, replace the script-tag assembly:
```python
def render_html(turns, subagent_count, subagent_cost, session_id,
                x_axis_mode, chartjs_inline_bytes,
                time_adapter_inline_bytes):
    if chartjs_inline_bytes is not None:
        chartjs_script_tag = f"<script>{chartjs_inline_bytes.decode('utf-8')}</script>"
    else:
        chartjs_script_tag = f'<script src="{CHARTJS_CDN_URL}"></script>'

    if x_axis_mode == "time":
        if time_adapter_inline_bytes is not None:
            time_adapter_script_tag = (
                f"<script>{time_adapter_inline_bytes.decode('utf-8')}</script>"
            )
        else:
            time_adapter_script_tag = f'<script src="{TIME_ADAPTER_CDN_URL}"></script>'
    else:
        time_adapter_script_tag = ""
    # ...rest of function unchanged...
```

In `main()`, before the `render_html` call:
```python
    chartjs_bytes = None
    time_adapter_bytes = None
    if arguments.inline_js:
        chartjs_bytes = _cached_download(
            CHARTJS_INLINE_URL,
            f"chart.js-{CHARTJS_INLINE_VERSION}.umd.min.js",
        )
        if arguments.x == "time":
            time_adapter_bytes = _cached_download(
                TIME_ADAPTER_INLINE_URL,
                "chartjs-adapter-date-fns-3.0.0.bundle.min.js",
            )
```

Then update the `render_html` call:
```python
    html_text = render_html(
        turns=turns,
        subagent_count=subagent_count,
        subagent_cost=subagent_cost,
        session_id=session_id,
        x_axis_mode=arguments.x,
        chartjs_inline_bytes=chartjs_bytes,
        time_adapter_inline_bytes=time_adapter_bytes,
    )
```

- [ ] **Step 2: Smoke-test inline mode, online and offline**

Online:
```
python scripts/plot-session.py <session-id-prefix> --inline-js --open
python scripts/plot-session.py <session-id-prefix> --inline-js --x time --open
```
Both should render identically to Task 6.

Offline:
- Disable network (turn off Wi-Fi or use `--block-network` equivalent).
- Open the previously written HTML file directly in the browser.
- Chart should still render. (CDN-mode files would fail; inline-mode files must succeed.)

Verify the cache path:
```
ls ~/.cache/cost-estimator/
```
Expected: `chart.js-4.4.7.umd.min.js` (and `chartjs-adapter-date-fns-3.0.0.bundle.min.js` if time mode was used).

- [ ] **Step 3: Commit**

```
git add scripts/plot-session.py
git commit -m "plot-session: support --inline-js for offline-viewable HTML"
```

---

## Phase 3: Documentation & end-to-end validation

### Task 8: Update `SKILL.md` to mention `plot-session.py`

**Files:**
- Modify: `SKILL.md` (3 small additions)

- [ ] **Step 1: Add a new step under "Steps" pointing at plot-session for top sessions**

Find the existing numbered "Steps" list (currently steps 1–5, ending at "Offer to save"). Insert a new step between current step 4 ("Synthesize a markdown report") and current step 5 ("Offer to save"):

```markdown
5. **Plot top spike sessions on demand.** When the report flags a
   top-N session that the user wants to investigate, render its
   per-turn trajectory:
   ```bash
   python <skill-root>/scripts/plot-session.py <session-id-prefix> --open
   ```
   This produces an HTML chart (per-turn bars + cumulative line +
   hover tooltips) at `<skill-root>/reports/session-<prefix>.html`,
   helping the user see *where* in the session the spike happened.
   Pass `--inline-js` for an offline-viewable file. Currently parent-
   only — subagent cost is summarized in the page caption but not
   plotted.
```

Renumber the existing step 5 ("Offer to save") to step 6.

- [ ] **Step 2: Add a Phase-2 caveat to "What this skill does not do (yet)"**

Find the existing "What this skill does not do (yet)" section. Add this bullet (placement: above or below the existing "Per-project breakdown" bullet, whichever reads better):

```markdown
- Subagent timeline overlays. `plot-session.py` plots the parent
  JSONL only; subagent costs are summarized in the chart caption but
  not plotted as their own anchored sub-trajectories. Adding overlay
  curves anchored to spawn/finish timestamps is a planned Phase 2.
```

- [ ] **Step 3: Update the "Files in this skill" list**

Find the bullet list at the end of `SKILL.md`. Add two bullets and revise the existing analyze-month bullet to mention pricing:

```markdown
- `scripts/pricing.py` — canonical pricing helpers (rates, multipliers,
  `cost_for_turn`, `iter_assistant_turns`). Both retrospective and
  per-session scripts import from here.
- `scripts/analyze-month.py` — JSONL walker and per-turn pricer
  (uses `pricing.py`). Default `--out` is `<skill-root>/reports/`.
- `scripts/summarize.py` — CSV reader and waste-pattern report.
  Default `--csv` is `<skill-root>/reports/sessions.csv`.
- `scripts/plot-session.py` — per-session HTML cost trajectory chart
  (uses `pricing.py`).
```

(Replace the existing analyze-month and summarize bullets with the four-bullet version above.)

- [ ] **Step 4: Commit**

```
git add SKILL.md
git commit -m "skill: document plot-session.py and pricing.py"
```

---

### Task 9: Update `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read the current README**

```
cat README.md
```

Identify where the existing scripts (analyze-month, summarize) are introduced. The README is a short overview file; the new mention should be one to two sentences.

- [ ] **Step 2: Add a brief mention of plot-session**

Add a paragraph or list entry near the existing tooling description:

```markdown
- **`scripts/plot-session.py`** — render a single session's per-turn
  cost trajectory as an interactive HTML chart (Chart.js). Useful for
  investigating a session that `summarize.py` flagged as a top
  spender; shows where in the session the cost actually accrued.
```

If the README has no list of scripts (only prose), insert a one-sentence reference matching the prose style.

- [ ] **Step 3: Commit**

```
git add README.md
git commit -m "readme: mention plot-session.py"
```

---

### Task 10: End-to-end cross-validation

**Files:**
- (No file changes — verification only)

- [ ] **Step 1: Run the full retrospective flow end-to-end**

```
python scripts/analyze-month.py ~/.claude/projects --month 2026-04 --label chonkers --out reports
python scripts/summarize.py
```

Sanity-check the printed totals are sensible.

- [ ] **Step 2: Pick a top-3 session from `summarize.py` output and plot it**

From the "TOP 20 SESSIONS" stdout, pick a session with high cost AND non-trivial subagent count. Note its 8-char prefix and its `Raw $` value.

```
python scripts/plot-session.py <prefix> --open
```

- [ ] **Step 3: Verify cumulative line endpoint matches sessions.csv**

Open `reports/sessions.csv`, find the row for that session. Compute the parent-only portion: `cost_usd - subagent_cost`. The chart's cumulative-line endpoint (top-right) should match this value to within rounding (~$0.0005).

If they match: the per-turn extraction and pricing path are correct end-to-end.
If they diverge: something is wrong. Most likely culprit is a dedup discrepancy between `iter_assistant_turns` and `process_file` in analyze-month.py — re-check those two should produce equivalent dedup behavior.

- [ ] **Step 4: Verify the page caption subagent stat matches sessions.csv**

The chart caption shows "Subagents: N dispatches, $X.XX aggregate". Compare to sessions.csv:
- `N` should match `subagent_count`.
- `$X.XX` should match `subagent_cost` to rounding.

- [ ] **Step 5: Verify --x time and --inline-js still work on this real session**

```
python scripts/plot-session.py <prefix> --x time --inline-js
```

Open the resulting HTML offline (turn off network briefly). Chart should render correctly with a wall-clock x-axis.

- [ ] **Step 6: No commit if everything passes**

If a divergence required a code fix, commit that fix with a clear message explaining what diverged and why. Otherwise nothing to commit at this step.
