# Aggregate trend graph — design

**Date:** 2026-05-10
**Skill:** cost-estimator
**Status:** draft (working spec for plan handoff)

## Goal

Add a trend chart that shows total Claude Code spend over an arbitrary
date range, stacked by machine, across one or more `.claude/projects`
roots. Closes the known gap noted in `SKILL.md` ("Trend over time
beyond daily. No weekly / month-over-month deltas"). Mirrors the
existing per-session chart's visual idiom (Chart.js mixed bar + line,
hover tooltips, `--inline-js`, `--open`).

## Non-goals

- Predictive cost estimation. Still deferred.
- Per-subagent overlay curves. Subagent cost is folded into the parent
  session's `cost_usd` by `analyze-month.py`, same fold this chart
  inherits.
- Per-project (slug) breakdown. The stack dimension is machine label
  only; per-project is a separate future extension.
- Trends on dimensions other than cost (e.g., turn counts, cache-hit
  rates over time). Out of scope.

## File layout

```
cost-estimator/scripts/
├── analyze-month.py     (modified — env-var root resolution)
├── plot-session.py      (modified — imports from chart_runtime)
├── plot-trend.py        (new — the aggregate chart)
├── chart_runtime.py     (new — ~40 lines, shared Chart.js bits)
├── pricing.py           (unchanged)
└── summarize.py         (unchanged)
```

### What goes in `chart_runtime.py`

Narrow extraction — only the pieces that would *literally* duplicate
between `plot-session.py` and `plot-trend.py` and must stay in sync
when Chart.js updates:

- `CHARTJS_CDN_URL`, `TIME_ADAPTER_CDN_URL`
- `CHARTJS_INLINE_VERSION`, `CHARTJS_INLINE_URL`
- `TIME_ADAPTER_INLINE_VERSION`, `TIME_ADAPTER_INLINE_URL`
- `_cached_download(url, cache_filename) -> bytes`
- `chartjs_script_tags(inline: bool, want_time_adapter: bool) ->
  (chartjs_tag, time_adapter_tag)` — returns the two `<script>`
  fragments, handling CDN vs inline.

The HTML template, per-chart metadata, and Chart.js config stay in
each plotter — they differ enough that sharing would mean awkward
placeholder dancing for negative win.

## Multi-root input + env-var resolution

This change lives entirely in `analyze-month.py`. By the time
`plot-trend.py` runs, roots are already resolved via the
`sessions.csv` it reads.

**Env-var format:**
`CLAUDE_COST_ROOTS="chonkers:C:/Users/mtsch/.claude/projects,llamabox:Y:/.claude/projects"`.
Comma-separated `label:path` pairs. The *first* colon in each pair is
the delimiter — anything after is the path, which preserves Windows
drive letters (`C:/...`).

**Precedence rule:**

1. Positional roots on CLI → use those; ignore env var entirely. If
   the env var is set and CLI roots are also given, print a single
   stderr line: `note: CLAUDE_COST_ROOTS set but CLI roots given; using CLI`.
2. No positional roots and `CLAUDE_COST_ROOTS` set → parse it, use
   those `(label, path)` pairs.
3. Neither → default to `[("local", ~/.claude/projects)]`.

CLI `--label` flags pair only with positional CLI roots (existing
behavior). Env-var pairs carry their labels inline.

**Parse failures** (no colon, empty label, empty path) exit 1 with a
message naming the offending entry: `error: CLAUDE_COST_ROOTS
malformed near '<entry>' (expected 'label:path')`.

**Missing paths** exit 1: `error: root not found: <path> (label=<label>)`.

## Range and bucketing

`plot-trend.py` flags mirror `analyze-month.py`:

- `--month YYYY-MM` *or*
- `--start YYYY-MM-DD --end YYYY-MM-DD` (end inclusive)

`--bucket {day,week,month}` overrides the auto-pick rule:

- range ≤ 14 days → `day`
- range ≤ 90 days → `week`
- range > 90 days → `month`

Bucket-key generation (pure Python, no extra deps):

- day: `dt.strftime("%Y-%m-%d")` → `"2026-04-12"`
- week: ISO week from `dt.isocalendar()` → `"2026-W15"` (year-week,
  not year-month-week — simpler and unambiguous)
- month: `dt.strftime("%Y-%b")` → `"2026-Apr"`

## Data flow inside `plot-trend.py`

```
sessions.csv (read; default <skill-root>/reports/sessions.csv,
              override with --csv <path>)
  ↓ filter rows where first_timestamp ∈ [range_start, range_end]
  ↓ bucket each row by first_timestamp (day/week/month)
  ↓ group: (bucket_key, label) → sum(cost_usd), count(sessions)
  ↓ pivot: one Chart.js dataset per machine label, zero-filled
            so stacks align across empty buckets
  ↓ build cumulative-total dataset (single line, right y-axis)
  ↓ embed as JSON literal in HTML template; render
```

### Columns used from `sessions.csv`

`label`, `first_timestamp` (ISO8601), `cost_usd`, `session_id`.
Confirmed against current `analyze-month.py` schema (fields at
lines 349–357 of `analyze-month.py`).

## Chart rendering

**Type:** mixed — `bar` datasets per machine on left y-axis, stacked;
one `line` dataset for cumulative total on right y-axis, not stacked.

**Scales:**

```js
scales: {
  x:  { stacked: true, type: 'category' },
  y:  { stacked: true, position: 'left',
        title: { display: true, text: 'Cost ($)' }, beginAtZero: true },
  y1: { position: 'right', grid: { drawOnChartArea: false },
        title: { display: true, text: 'Cumulative ($)' }, beginAtZero: true }
}
```

Category x-axis avoids the known sparsity-with-bars gotcha that the
Chart.js `type: 'time'` axis has when stacked bars span uneven
intervals.

**Color discipline:** stable, label-keyed palette. Hash the label
string into an 8-entry palette so `chonkers` is always the same color
across reports. If a user has >8 machines, collisions are tolerated
with a one-line stderr note.

**Hover tooltips:**

- per stacked segment: `chonkers · 2026-04-12 · $8.42 · 3 sessions`
- bar background: `Total: $12.31 · 5 sessions across 2 machines`
- cumulative point: `Cumulative through 2026-04-12: $84.20`

**Meta row at top of HTML:** `Range: 2026-04-01 → 2026-04-30 | Bucket:
day | Total: $187.42 | Sessions: 64 | Machines: chonkers ($112.10,
41), llamabox ($75.32, 23)`.

**Footnote:** `Trend chart aggregates per-session costs from
sessions.csv; subagent costs are folded into their parent session's
total (no separate subagent series).`

**Output path default:** `<skill-root>/reports/trend-<range>.html`,
where `<range>` is `YYYY-MM` for `--month` invocations or
`YYYY-MM-DD_YYYY-MM-DD` for arbitrary range.

## CLI surface

```
python plot-trend.py
    (--month YYYY-MM | --start YYYY-MM-DD --end YYYY-MM-DD)
    [--bucket {day,week,month}]
    [--csv <path>]               # default: <skill-root>/reports/sessions.csv
    [--inline-js]                # offline-viewable HTML
    [--out <path>]               # default: <skill-root>/reports/trend-<range>.html
    [--open]                     # open in default browser
```

`--month` and `--start/--end` are mutually exclusive (argparse group).
No root flags — those live in `analyze-month.py`.

## Error handling

- Missing `sessions.csv`: `error: sessions.csv not found at <path>.
  Run analyze-month.py first, or pass --csv <path>.` Exit 1.
- Empty range: `error: no sessions in range <start> → <end> (csv has
  N rows total, span <min>...<max>).` Exit 1, show the actual span.
- Malformed `first_timestamp`: skip row, count, warn once at end —
  don't fail.
- `--month` and `--start/--end` both passed: argparse mutual-exclusion.
- Output dir missing: `mkdir(parents=True, exist_ok=True)`, same as
  `plot-session.py`.
- `--inline-js` download fails: let `_cached_download` raise with the
  URL in the message.

## Testing

1. **Unit smoke for bucketing.** `scripts/test_buckets.py` imports the
   bucket-key function from `plot-trend.py` and asserts: day case,
   month case, ISO week boundary (2024-12-30 → `"2025-W01"`, since
   ISO week 1 is the week containing the first Thursday; 2024-12-30
   is the Monday of that week). Pure-function, runs in milliseconds.
2. **End-to-end smoke.** Run against real `sessions.csv` for `--month
   2026-04`: HTML opens, stacks render, total matches `summarize.py`'s
   top-level number for the same range. Repeat with `--bucket week`,
   `--bucket month`, `--inline-js --open`.
3. **Env-var smoke.** Unset `CLAUDE_COST_ROOTS`, run `analyze-month.py`
   no-args → defaults to local. Set to a malformed pair → clear error.
   Set to a missing path → clear error.
4. **`plot-session.py` regression.** After `chart_runtime.py`
   extraction, diff produced HTML against pre-refactor copy on one
   known session. Functionally identical.

## SKILL.md and README updates

- Remove "Trend over time beyond daily" from the "What this skill does
  not do (yet)" list.
- Add a step to the main flow describing when to invoke
  `plot-trend.py` (after `analyze-month.py` + `summarize.py`, when the
  user wants to see how spend shifted over the range).
- Document `CLAUDE_COST_ROOTS` env var in the "Inputs to gather from
  the user" section.
- Add a `plot-trend.py` entry to the "Files in this skill" list.
- README: add a paragraph mirroring the `plot-session.py` section,
  with an embedded screenshot of a sample trend chart.

## Open follow-ups (not in scope here)

- Per-project (slug) stack dimension. Would need `parent_path` →
  project-slug bucketing in `analyze-month.py`.
- Per-subagent overlay curves on the trend chart. Probably more useful
  on `plot-session.py` first.
- Side-by-side range comparison (this-month vs last-month overlay).
