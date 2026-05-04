---
name: cost-estimator
description: Use when the user asks for a retrospective Claude Code spend analysis over a date range — what they spent, top sessions, cache discipline, waste patterns, subscription leverage. Triggers include "/cost estimate", "what did I spend", "how much did last month cost", "cost breakdown", "where did my Claude budget go", "analyze my Claude spending", "audit my Claude usage". Walks local session JSONLs (parents and subagents), prices each turn per the canonical Anthropic rate table (Opus / Sonnet / Haiku with 1M-tier doubling, cache read 0.1x, cache write 1.25x), and produces per-session, daily, and waste-pattern reports. Predictive cost estimation ("how much will this plan cost") is not yet built — see ../README.md for the planned design.
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
is not yet built — point at `../README.md` and say so.

## Inputs to gather from the user

Most invocations need three things; ask only when not obvious:

1. **Date range.** Accept any of: a YYYY-MM month ("April 2026", "2026-04",
   "last month"), or an explicit YYYY-MM-DD start/end pair. Convert
   relative phrases to absolute dates before calling the script.
2. **Projects roots.** Default to `~/.claude/projects` on the current
   host. If the user works across multiple machines, ask whether to
   include other roots — typically a network-mounted path to another
   host's `~/.claude/projects`. The user's CLAUDE.md often documents
   the cross-machine convention; consult it before guessing.
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
   a brief stderr summary.
3. Run the deeper summary:
   ```bash
   python <skill-root>/scripts/summarize.py [--paid <usd>]
   ```
   Pass `--paid` only if the user supplied an actually-paid amount. The
   summary prints subagent-vs-parent reconciliation, top tool calls,
   first-turn input bloat, top-N sessions, daily totals, and (when
   `--paid` is set) leverage and prorated columns.
4. **Synthesize a markdown report** for the user. Follow
   `../REPORT_TEMPLATE.md` — it specifies every section to include
   (headline, leverage, top sessions, top tool calls, first-turn bloat,
   daily totals, things-to-avoid walkthrough, methodology). Don't drop
   sections to save space; the value of the report is precisely that it
   surfaces patterns the user wouldn't see in a one-line summary. Pull
   each section from the corresponding part of summarize.py's stdout.
   Always label raw vs prorated explicitly — never leave it ambiguous.
5. **Offer to save.** If the analysis was substantive, save the report
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

- Predict cost for a future task. A predictive companion is in design
  at `../README.md` (uses `count_tokens` API + heuristics + the
  historical `sessions.csv` as a reference dataset).
- Per-project breakdown. The analyzer groups by machine label, not by
  project slug. Easy extension: bucket `parent_path` by its containing
  directory in a follow-up summary.
- Trend over time beyond daily. No weekly / month-over-month deltas.

## Files in this skill

- `skill-draft/SKILL.md` — this file.
- `../README.md` — top-level overview + predictive-half design.
- `../REPORT_TEMPLATE.md` — section-by-section template for the
  markdown report this skill produces. Follow it.
- `../scripts/analyze-month.py` — JSONL walker and per-turn pricer.
  Default `--out` is `../reports/`.
- `../scripts/summarize.py` — CSV reader and waste-pattern report.
  Default `--csv` is `../reports/sessions.csv`.
- `../reports/` — gitignored. All analyzer outputs (`sessions.csv`,
  `daily.csv`, `summary.txt`) and synthesized reports go here.
