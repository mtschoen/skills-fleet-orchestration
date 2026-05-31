---
name: cost-estimator
description: Use when the user asks for a retrospective Claude Code spend analysis over a date range — what they spent, top sessions, cache discipline, waste patterns, subscription leverage. Triggers include "/cost estimate", "what did I spend", "how much did last month cost", "cost breakdown", "where did my Claude budget go", "analyze my Claude spending", "audit my Claude usage". Walks local session JSONLs (parents and subagents), prices each turn per the canonical Anthropic rate table (Opus / Sonnet / Haiku with 1M-tier doubling, cache read 0.1x, cache write 1.25x), and produces per-session, daily, and waste-pattern reports. Predictive cost estimation ("how much will this plan cost") is not yet built — see github.com/mtschoen/skills-cost-estimator for the planned design.
---

# cost-estimator (retrospective)

This skill answers "what did I spend on Claude Code over [some date range]?"
It walks the local session transcripts and produces a defensible cost
breakdown that goes beyond `/cost` (current session only) and `ccusage`
(no 1M-tier modeling, no per-machine grouping, no waste-pattern flags).

## When to invoke

The user's intent is retrospective spend analysis when they say things
like "what did I spend last month", "/cost estimate April", "audit my
Claude usage", "where did my budget go", "show me my top sessions",
"break down my spending". If they instead ask "how much will THIS cost"
about something they have not yet run, that is the predictive case which
is not yet built — point the user at
<https://github.com/mtschoen/skills-cost-estimator> for design notes
and say so.

## Inputs to gather from the user

Most invocations need three things; ask only when not obvious:

1. **Date range.** Accept any of: a YYYY-MM month ("April 2026", "2026-04",
   "last month"), or an explicit YYYY-MM-DD start/end pair. Convert
   relative phrases to absolute dates before calling the script.
2. **Projects roots.** Default to `~/.claude/projects` on the current
   host. If the user works across multiple machines, ask whether to
   include other roots — typically a network-mounted path to another
   host's `~/.claude/projects`. The user's AGENTS.md (or CLAUDE.md) often documents
   the cross-machine convention; consult it before guessing.

   Multi-machine setups can set the `CLAUDE_COST_ROOTS` env var once
   (format: `"label1:path1,label2:path2"`) — analyze-month.py picks it
   up automatically when no positional roots are given. CLI args
   always win when both are present.
3. **Actually paid (optional).** If the user wants prorated cost
   alongside raw, ask what they paid that period (Max plan tier + any
   extra usage). Without it, the script reports raw only — that is
   fine when the user only cares about API-equivalent value.

## Steps

1. Resolve the date range. For a whole month, pass `--month YYYY-MM`.
   For arbitrary ranges, pass `--start YYYY-MM-DD --end YYYY-MM-DD` (end
   is inclusive).
2. Run the analyzer:

   ```bash
   python <skill-root>/scripts/analyze-month.py \
       <root-1> [<root-2> ...] \
       --month <YYYY-MM>           # OR --start ... --end ...
       --label <name-1> [--label <name-2> ...]
   ```

   This writes `sessions.csv` and `daily.csv` next to the script (both
   are gitignored by the parent `cost-estimator/.gitignore`) and prints
   a brief stderr summary. It also prints a **"COVERAGE vs /stats"**
   section: a guardrail that flags when surviving transcripts undercount
   the range because old days were cache-cleared (transcripts
   garbage-collected under the old 30-day retention). When it warns, the
   dollar total is a **floor** — carry that into the report (step 4), and
   drill in with `stats_cache.py` (step 8) for the per-day breakdown.
3. Run the deeper summary:

   ```bash
   python <skill-root>/scripts/summarize.py [--paid <usd>]
   ```

   Pass `--paid` only if the user supplied an actually-paid amount. The
   summary prints subagent-vs-parent reconciliation, top tool calls,
   first-turn input bloat, top-N sessions, daily totals, and (when
   `--paid` is set) leverage and prorated columns.
4. **Synthesize a markdown report** for the user. Follow
   `REPORT_TEMPLATE.md` — it specifies every section to include
   (headline, coverage/confidence, leverage, top sessions, top tool
   calls, first-turn bloat, daily totals, things-to-avoid walkthrough,
   methodology). Don't drop sections to save space; the value of the
   report is precisely that it surfaces patterns the user wouldn't see
   in a one-line summary. Pull each section from the corresponding part
   of summarize.py's stdout — except the coverage section, which comes
   from analyze-month.py's "COVERAGE vs /stats" output. Always label raw
   vs prorated explicitly, and if coverage warned, label the total a
   floor — never leave either ambiguous.
5. **Plot top spike sessions on demand.** When the report flags a
   top-N session that the user wants to investigate, render its
   per-turn trajectory:

   ```bash
   python <skill-root>/scripts/plot-session.py <session-id-prefix> --open
   ```

   This produces an HTML chart (per-turn bars + cumulative line +
   hover tooltips) at `<skill-root>/reports/session-<prefix>.html`,
   helping the user see *where* in the session the spike happened.
   Pass `--inline-js` for an offline-viewable file. Pass `--x time`
   to render the x-axis as wall-clock time instead of turn number —
   useful for sessions with long idle gaps. Currently plots the
   parent JSONL only — subagent cost appears in the page caption but
   not as overlay curves.
6. **Plot the aggregate trend across the range.** Run after
   analyze-month.py so the CSV exists:

   ```bash
   python <skill-root>/scripts/plot-trend.py \
       (--month YYYY-MM | --start YYYY-MM-DD --end YYYY-MM-DD) \
       [--bucket {day,week,month}] [--inline-js] [--open]
   ```

   Produces an HTML chart at `<skill-root>/reports/trend-<range>.html`.
   Bars stack per-machine cost in each bucket; right-axis line shows
   the cumulative total. Bucket size auto-picks from range length
   (≤14d→day, ≤90d→week, >90d→month) or override with `--bucket`.
7. **Compare two windows side-by-side.** When the user asks "is my
   spend trending up/down?" or "how does this week compare to last?",
   render the period-over-period overlay:

   ```bash
   python <skill-root>/scripts/plot-compare.py \
       (--month YYYY-MM | --start YYYY-MM-DD --end YYYY-MM-DD | --last <Nh|Nd>) \
       [--bucket {day,week,month}] [--inline-js] [--open]
   ```

   The prior window is auto-derived as the same-length window
   immediately before the current one. Bucket-index (Day/Week/Month N)
   makes paired bars apples-to-apples wall-clock-relative slices, not
   calendar-aligned. Output lands in `<skill-root>/reports/compare-<range>.html`.
8. **Reconcile against /stats on demand.** When the coverage warning
   fires (or the user asks "why doesn't this match /stats?"), run the
   full per-day reconciliation:

   ```bash
   python <skill-root>/scripts/stats_cache.py \
       <root-1> [<root-2> ...] \
       (--month YYYY-MM | --start YYYY-MM-DD --end YYYY-MM-DD) \
       [--label <name-1> ...] [--threshold 0.90]
   ```

   Prints, per machine: the `stats-cache.json` `modelUsage` inventory, a
   per-day `/stats`-vs-transcript table (match / partial / cleared), and
   the coverage %. `cleared` days are ones whose transcripts were
   garbage-collected — `/stats` `dailyModelTokens` is their only
   surviving record (in+out only, no cache, no dollars). The comparison
   is raw-vs-raw (both non-deduped, verified equal to the token on intact
   days), so a fully-present range reads ~100%. Use this to *explain* the
   gap, not to "fix" the dollar total — cleared days genuinely cannot be
   priced. Roots/stats files are resolved exactly like analyze-month.py
   (`CLAUDE_COST_ROOTS` or positional roots; the stats file is the
   sibling `stats-cache.json` of each projects root).
9. **Probe cache TTL on demand.** If the user asks whether their cache is
   1h- or 5m-TTL, or why cache-write cost looks high:

   ```bash
   python <skill-root>/scripts/cache_ttl.py <root-1> [<root-2> ...]
   ```

   Reports the `ephemeral_5m` vs `ephemeral_1h` split of cache-write
   tokens and a behavioral inter-turn-gap table (a high "miss%" in the
   5–60m buckets would betray a 5m TTL letting prefixes expire).
   Subscription accounts write 1h-TTL by default.
10. **Offer to save.** If the analysis was substantive, save the report
   to `<skill-root>/reports/<range>.md`. That folder (and everything in
   it) is gitignored. Capture the summary.txt alongside via shell
   redirect:

   ```bash
   python <skill-root>/scripts/summarize.py [--paid <usd>] \
       > <skill-root>/reports/summary.txt
   ```

## What "things to avoid" looks like in this skill's output

The data lets you flag four classes of waste. Walk through each in the
report and either point at culprits or explicitly state "no problem
here":

- **Cache discipline.** From `sessions.csv` look at sessions with
  `cost_usd >= 5` and `cache_hit_pct < 70`. If the list is empty, say
  so — that is itself a useful finding.
- **Skill / MCP loader bloat.** `first_turn_input_tokens` proxies the
  system-prompt + tool-schema payload paid on every fresh session. The
  summary script ranks the worst offenders. Above ~50K is suspicious
  and worth flagging the slug for the user to investigate.
- **Subagent fan-out.** `subagent_count` and `subagent_cost` per
  session. High counts are healthy when matched by high turn counts;
  high subagent cost in short sessions indicates unproductive fan-out.
- **Repeat tool patterns.** The summary's "tools called in >50% of
  sessions and >1000 calls" section lists candidates that would benefit
  from skill or memory wrapping. An empty list means existing
  skills/memory are doing their job.

## Cross-validation discipline

Always show the user that the number is defensible. The summary script
already prints subagent-vs-parent breakdowns. When the user asks about
a single specific number, also report what `ccusage monthly` says for
the same range — they will diverge by a few percent (this script
applies the 1M-context-tier rate doubling that ccusage does not, so
this script reads slightly hot when there is heavy `[1m]` traffic).
Bracket the truth between the two values rather than asserting one.

## Pricing table (canonical, inlined)

The analyzer applies these rates per million tokens. Source of truth is
`~/.claude/notes/reference_anthropic_pricing.md`; the table here is
duplicated for skill self-containment.

| Family | Input | Output |
|---|---|---|
| Opus 4.5 / 4.6 / 4.7 | $5  | $25 |
| Sonnet 4.5 / 4.6     | $3  | $15 |
| Haiku 4.5            | $1  | $5  |

Cache multipliers (relative to base input rate, all models): cache read
**0.1x**, cache write **1.25x** (empirical for both 5m and 1h TTLs as of
2026-04, despite docs claiming 2.0x for 1h-TTL writes).

The 1M-context tier (when `model.id` contains `[1m]`) doubles input and
output rates. Cache multipliers stay relative to the doubled base.

## What this skill does not do (yet)

- Predict cost for a future task. A predictive companion is in design;
  see <https://github.com/mtschoen/skills-cost-estimator> for the
  build path (uses `count_tokens` API + heuristics + the historical
  `sessions.csv` as a reference dataset).
- Subagent timeline overlays. `plot-session.py` plots the parent
  JSONL only; subagent costs are summarized in the chart caption but
  not plotted as their own anchored sub-trajectories. Adding overlay
  curves anchored to spawn/finish timestamps is a planned Phase 2.
- Per-project breakdown. The analyzer groups by machine label, not by
  project slug. Easy extension: bucket `parent_path` by its containing
  directory in a follow-up summary.
- Dollar backfill of cache-cleared days. `stats_cache.py` *detects* and
  *quantifies* cleared days (coverage %, cleared in+out tokens) but does
  not estimate their dollars. `/stats` `dailyModelTokens` is raw
  (non-deduped, ~3.2× hot), carries no input/output split (only a
  per-model in+out sum), and excludes cache entirely — so any backfilled
  dollar figure would be a coarse guess stacked on three approximations.
  Deferred until that estimation can be designed deliberately; for now
  the floor + the cleared-token count is the honest answer.

## Files in this skill

- `SKILL.md` — this file.
- `REPORT_TEMPLATE.md` — section-by-section template for the markdown
  report this skill produces. Follow it.
- `scripts/pricing.py` — canonical pricing formula (rates, cache
  multipliers, 1M-tier doubling) plus the JSONL turn-iterator helper.
  Both retrospective and per-session scripts import from here so the
  formula does not drift.
- `scripts/analyze-month.py` — JSONL walker and per-turn pricer
  (uses `pricing.py`). Default `--out` is `<skill-root>/reports/`.
  Also prints the "COVERAGE vs /stats" guardrail (uses `stats_cache.py`).
- `scripts/roots.py` — shared root resolution (`CLAUDE_COST_ROOTS` /
  positional roots), date-bound parsers, and `stats_file_for()`.
  Imported by `analyze-month.py`, `stats_cache.py`, and `cache_ttl.py`
  so path/range logic stays in one place.
- `scripts/stats_cache.py` — reconciles surviving transcripts against
  Claude Code's per-machine `/stats` aggregate (`stats-cache.json`).
  Flags cache-cleared (garbage-collected) days and reports coverage %,
  so a report never silently presents an undercount as the full total.
  Exposes `coverage_for_roots` / `format_warning` for the analyze-month
  guardrail, plus a standalone per-day reconciliation CLI.
- `scripts/cache_ttl.py` — diagnostic for cache-write TTL (5m vs 1h
  split) and an inter-turn-gap behavioral table.
- `scripts/summarize.py` — CSV reader and waste-pattern report.
  Default `--csv` is `<skill-root>/reports/sessions.csv`.
- `scripts/plot-session.py` — per-session HTML cost trajectory chart
  (uses `pricing.py`).
- `scripts/plot-trend.py` — aggregate trend chart across sessions.csv
  (uses `chart_runtime.py`). Stacks by machine label.
- `scripts/plot-compare.py` — period-over-period overlay chart.
  Renders any window vs the same-length prior window (--month /
  --start+--end / --last). Imports bucket helpers from `trend_data.py`.
- `scripts/trend_data.py` — shared bucket math, CSV reader, and range
  parsers. Imported by plot-trend.py and plot-compare.py so the same
  bucketing logic stays in one place.
- `scripts/chart_runtime.py` — shared Chart.js URL/version constants,
  download cache, and script-tag helper used by both plot scripts.
- `reports/` — created on demand by the scripts; holds CSVs and
  synthesized reports. Gitignored in the source repo.
