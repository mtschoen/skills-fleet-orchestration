# cost-plot-session — design spec

**Date:** 2026-05-06
**Status:** Draft, pre-implementation
**Project:** cost-estimator (skill submodule of skills-dev)

## Problem

The retrospective half of cost-estimator gives per-session totals (`sessions.csv`), per-day totals (`daily.csv`), and aggregate waste-pattern reports (`summarize.py`). What it does not give: how cost evolved *within* a single session, turn by turn. When `summarize.py` flags a $40 session as a top spender, the natural next question is "where in the session did the spend happen — was it one runaway turn, a slow climb, or a bloated first turn?" Today there is no way to answer that without writing ad-hoc one-off scripts.

The user wants to point the skill at a particular session ID (or JSONL path) and get back a chart of cost over the course of that session. The triggering use case is "summarize.py flagged this session — show me the trajectory," but the same view is also useful for "I just had an expensive session" and "let me compare a couple sessions side-by-side" workflows.

## Scope & phasing

### Phase 1 (this work)

A new script `scripts/plot-session.py` that renders one session's cost trajectory as an HTML chart. The chart shows:

- **Bars (left y-axis):** per-turn cost in USD.
- **Line (right y-axis):** cumulative cost in USD across the session.
- **Hover tooltip:** turn number, timestamp, model, top tools used, input/output/cache tokens, and the turn's cost.
- **X-axis:** turn number by default (`--x turn`); wall-clock timestamp via `--x time`.

Phase 1 plots the **parent JSONL only**. Subagent JSONLs are *not* parsed for the timeline. To prevent the user from being misled into thinking they see the full session cost, the page caption shows a summary stat: number of subagent dispatches and their aggregate cost (parsed from sibling subagent JSONL files, but not plotted on the timeline). When subagent cost is significant, the caption makes it obvious there is more spend off-chart.

### Phase 2 (deferred — not built in this work)

Subagent sub-trajectory curves overlaid on the parent timeline, anchored to their actual spawn and finish points (each subagent gets its own thin cumulative-cost line that starts when its `Task` tool_use was issued and ends when its last assistant turn timestamp lands). This is genuinely useful but materially more complex: it requires linking the parent's `Task` tool_use blocks to subagent JSONL files via the sibling `<agent-id>.meta.json` sidecars, and arranging multiple curves on a wall-clock x-axis without visual chaos.

Phase 2 is mentioned as a known follow-up in `SKILL.md`'s "what this skill does not do (yet)" list. Phase 1 is structured so that adding Phase 2 later is a strict additive change — the parent timeline does not need to be redesigned to accommodate it.

## Architecture

### Shared pricing module

`scripts/analyze-month.py` currently owns the canonical pricing logic: `model_family`, `is_one_million_tier`, `parse_timestamp`, and `cost_for_turn`. The new `plot-session.py` needs the same formula. Rather than copy-paste (which would create a real drift risk in a skill whose value is precisely that the formula is correct and defensible), extract the four functions plus the `PRICES` / multiplier constants into a new module:

- **NEW:** `scripts/pricing.py` — owns `PRICES`, `CACHE_READ_MULTIPLIER`, `CACHE_WRITE_MULTIPLIER`, `model_family`, `is_one_million_tier`, `parse_timestamp`, `cost_for_turn`.
- **MODIFY:** `scripts/analyze-month.py` — delete those definitions and `from pricing import ...` instead. Behavior unchanged; the existing CSV outputs must remain byte-identical for the same input.

This is the kind of targeted improvement the brainstorming skill calls for: small, in-scope, removes a specific risk that affects this work.

### New script: plot-session.py

`scripts/plot-session.py` is responsible for:

1. Resolving the user's session argument to a parent JSONL path.
2. Walking that JSONL once, extracting per-assistant-turn rows with the same dedupe-by-`message.id` logic the existing analyzer uses.
3. Computing each turn's `cost_usd` via `pricing.cost_for_turn`, plus a running `cumulative_cost`.
4. Optionally counting subagent files and totaling their cost, for the caption stat only.
5. Rendering an HTML page with Chart.js (loaded from CDN by default, embeddable via `--inline-js`) and writing it to `<skill-root>/reports/session-<id-prefix>.html`.

## CLI

```
python plot-session.py <session-id-or-jsonl-path>
    [--projects <root> ...]    # default: ~/.claude/projects on the current host
    [--x {turn,time}]           # default: turn
    [--inline-js]               # embed Chart.js into the HTML; default uses CDN
    [--out <path>]              # default: <skill-root>/reports/session-<id-prefix>.html
    [--open]                    # open the resulting HTML in the default browser
```

**Argument resolution:**

- If `<session-id-or-jsonl-path>` exists on the filesystem and ends in `.jsonl`, treat it as a path.
- Otherwise treat it as a session ID (or a unique prefix). Walk each `--projects` root, looking for `<root>/<slug>/<id>.jsonl`. Error out with a clear message if 0 matches or >1 matches are found.
- If `--projects` is not given, default to `~/.claude/projects` on the current host (the same default the existing analyzer uses).

**Defaults rationale:**

- Turn-number x-axis as default because for cost analysis "turn 47 was the spike" is more actionable than "12:34pm was the spike" — turn numbers cross-reference the JSONL line-by-line.
- CDN as default because the install footprint stays zero. `--inline-js` exists for the email-this-to-someone-with-no-network case.

## Per-turn data extraction

`pricing.iter_assistant_turns(jsonl_path)` (new helper, lives in `pricing.py` so subagent-aware Phase 2 can use it too) yields one record per assistant turn:

```python
{
  "index": int,                # 1-based turn number within this JSONL
  "timestamp": str,            # ISO 8601, UTC
  "model": str,                # e.g. "claude-opus-4-7" or "claude-opus-4-7[1m]"
  "input_tokens": int,
  "output_tokens": int,
  "cache_read_tokens": int,
  "cache_write_tokens": int,
  "cost_usd": float,           # priced via cost_for_turn
  "top_tools": list[str],      # tool names in tool_use blocks of this turn, deduped, ordered by first-appearance
}
```

Dedupe-by-`message.id` is identical to the existing analyzer (turns recur in JSONL snapshots; naive iteration double-counts). Turns with no `message.id` are kept and counted (matches analyzer behavior).

`plot-session.py` consumes that iterator, accumulates `cumulative_cost`, and serializes the rows to JSON for the HTML payload.

## HTML output

A single Python triple-quoted-string template, formatted with `str.format` or `%`-formatting (no Jinja dependency). Structure:

```
<html>
  <head>
    <meta charset="utf-8">
    <title>Session <id-prefix> — cost trajectory</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <!-- or inline if --inline-js -->
    <style>...minimal CSS for layout, monospace meta line...</style>
  </head>
  <body>
    <h1>Session <id-prefix></h1>
    <div class="meta">
      <span>Date: <first-turn-date></span>
      <span>Total: $<total-cost></span>
      <span>Turns: <N></span>
      <span>Models: <comma-separated "family:total-tokens" pairs, e.g. "opus:1234567,sonnet:23456"></span>
      <span>Subagents: <count> dispatches, $<subagent-cost> aggregate</span>
    </div>
    <canvas id="chart" width="1200" height="500"></canvas>
    <script>
      const turns = /* JSON dump of per-turn records */;
      // Build datasets: bars on yLeft, line on yRight.
      // Tooltip callback reads turn record by index for rich detail.
      new Chart(document.getElementById('chart'), {
        type: 'bar',
        data: {
          labels: turns.map(t => /* turn number or timestamp depending on --x */),
          datasets: [
            {
              type: 'bar',
              label: 'Per-turn cost',
              data: turns.map(t => t.cost_usd),
              yAxisID: 'yLeft',
            },
            {
              type: 'line',
              label: 'Cumulative cost',
              data: turns.map(t => t.cumulative_cost),
              yAxisID: 'yRight',
              tension: 0.1,
            },
          ],
        },
        options: {
          scales: {
            yLeft:  { position: 'left',  title: { display: true, text: 'Turn cost (USD)' } },
            yRight: { position: 'right', title: { display: true, text: 'Cumulative cost (USD)' }, grid: { drawOnChartArea: false } },
          },
          plugins: {
            tooltip: {
              callbacks: {
                afterBody: (items) => {
                  const t = turns[items[0].dataIndex];
                  return [
                    `Model: ${t.model}`,
                    `Tools: ${t.top_tools.join(', ') || '(none)'}`,
                    `Input: ${t.input_tokens.toLocaleString()}  Output: ${t.output_tokens.toLocaleString()}`,
                    `Cache read: ${t.cache_read_tokens.toLocaleString()}  Cache write: ${t.cache_write_tokens.toLocaleString()}`,
                    `Timestamp: ${t.timestamp}`,
                  ];
                },
              },
            },
          },
        },
      });
    </script>
  </body>
</html>
```

The cumulative running total is computed Python-side (not JS-side) so the HTML payload is self-contained data, not a reduce expression that needs to be re-derived for Phase 2.

`--inline-js`: download Chart.js once into a `~/.cache/cost-estimator/chartjs-<version>.min.js` file (cache key on version), embed its bytes into a `<script>...</script>` tag in place of the CDN reference. ~50KB. Subsequent runs read from cache; no network.

## Files touched

| File | Status | Purpose |
|---|---|---|
| `scripts/pricing.py` | NEW | Shared pricing constants + helpers (`cost_for_turn`, `model_family`, `is_one_million_tier`, `parse_timestamp`, `iter_assistant_turns`). |
| `scripts/plot-session.py` | NEW | The new entry point. ~150 lines. |
| `scripts/analyze-month.py` | MODIFY | Delete extracted helpers, import from `pricing`. CSV outputs unchanged byte-for-byte. |
| `SKILL.md` | MODIFY | Add a step under "Steps" pointing at `plot-session.py` for top-N sessions surfaced by `summarize.py`. Add Phase-2 caveat to the "what this skill does not do (yet)" list. List `plot-session.py` and `pricing.py` in "Files in this skill". |
| `README.md` | MODIFY | One-liner mention. |
| `reports/` | UNCHANGED | Already gitignored; HTML files land here. |

## Testing & validation

No automated tests — the existing skill has none, the value here is visual, and the per-turn pricing logic is exercised end-to-end by the cross-check below.

**Cross-validation steps the implementer must run before declaring done:**

1. Pick a recent expensive session of mine that `summarize.py` has already costed. Run `plot-session.py <id>`. Confirm the cumulative line's final value matches `sessions.csv`'s `cost_usd` for that session to within rounding (the pricing formula is the same; this verifies the iterator and dedup logic.)
2. Hover a few representative turns; sanity-check that bar heights + tokens + model match the underlying JSONL.
3. Run `--x time`. Confirm gaps appear where I took breaks during the session.
4. Run `--inline-js`, open the resulting HTML offline (disable network), confirm chart still renders.
5. Re-run the existing `analyze-month.py` against a small range, confirm `sessions.csv` is byte-identical to a pre-refactor run on the same input. (Smoke-tests the pricing extraction.)

## Out of scope

- Subagent timeline overlays (Phase 2).
- Multi-session comparison views (mentioned as a use case but the user agreed Phase 1 = single-session; comparison is just "open two HTML files side by side").
- Predictive cost estimation (separate skill, separate repo).
- Per-project breakdowns (different feature, called out in existing SKILL.md).

## Open questions

None at the time of writing. All design choices have been resolved with the user during brainstorming.
