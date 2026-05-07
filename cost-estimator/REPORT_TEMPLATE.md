# Cost Analysis: {RANGE_LABEL}

Generated {YYYY-MM-DD} from local JSONLs on {MACHINE_LIST}.

All dollar figures are **raw API-equivalent token cost** unless explicitly
labelled prorated. {IF --paid SUPPLIED: "Prorated cost = raw × {DISCOUNT_FACTOR} (the implied subscription discount factor)."}

## Headline numbers

| | Raw cost | Sessions | Cache hit |
|---|---|---|---|
| {LABEL_1} | ${COST} | {N} | {HIT}% |
| {LABEL_2} | ${COST} | {N} | {HIT}% |
| **Total** | **${TOTAL}** | **{N}** | **{HIT}%** |

## Subscription leverage

*Include this section only when the user supplied --paid.*

| | |
|---|---|
| Raw token cost (analyzer) | **${RAW}** |
| Actually paid | **${PAID}** |
| Leverage | **{X}×** |
| Implied prorate factor | **{F}** |

Subagent spend was ${SUB} ({PCT}% of total).

## Cross-validation against ccusage

*Include this section only when ccusage was actually run for the same range.*

`ccusage monthly --since YYYYMMDD --until YYYYMMDD` reports ${CCUSAGE_TOTAL}
across {LABELS}. Analyzer reports ${ANALYZER_TOTAL} — delta {DELTA}%.
Where they disagree, this analyzer reads slightly hot because it doubles
rates for `[1m]` (1M-context tier) traffic which ccusage does not model.
Treat **${LOW}–${HIGH}** as the honest bracketed range.

## Top sessions

Source: top-N rows from `sessions.csv`.

| Date | Session | Raw | Prorated | Hit | Sub | Turns | Top tools |
|---|---|---|---|---|---|---|---|
| YYYY-MM-DD | {ID} ({label}) | $X | $Y | Z% | N | T | {Tool:N, ...} |
| ... | | | | | | | |

If the user asked about a specific session, include the absolute path:
- Parent: `<roots>/<slug>/<session-id>.jsonl`
- Subagents: `<roots>/<slug>/<session-id>/subagents/agent-*.jsonl`

## Top tool calls (across all sessions)

Source: "TOP TOOL CALLS" section of summarize.py output.

| Tool | Calls | Sessions | Coverage |
|---|---|---|---|
| Bash | 11,417 | 279/739 | 37.8% |
| ... | | | |

Highlight any MCP tools concentrated in a small number of expensive
sessions — those are typical "specialized work" patterns (e.g. Unity
sessions, web automation), not waste.

## First-turn input bloat (skill / MCP loader proxy)

Source: "FIRST-TURN INPUT TOKENS" section.

- Sum across all sessions: {X} tokens
- Mean: {Y}    Median: {Z}

Top 10 sessions by opening payload size (system prompt + tool schemas
paid on the first turn of every fresh session):

| Tokens | Cost | Hit % | Session | Machine |
|---|---|---|---|---|
| ... | | | | |

Anything over ~50K is worth investigating — that fresh-session toll
gets paid every time the conversation restarts. Shaving auto-loaded
plugins/MCPs/skills compounds across sessions.

## Daily totals

Source: `daily.csv` (or "DAILY TOTALS" section of summarize.py output).

| Date | Sessions | Raw $ | Prorated $ | Subagent $ | Subagents | Machines |
|---|---|---|---|---|---|---|
| YYYY-MM-DD | N | $X | $Y | $Z | M | hostA+hostB |

Drop the prorated column when --paid was not supplied.

## Things to avoid — what the data shows

Walk through the four classes below. Either point at culprits or
explicitly state "no problem here" — both are useful findings.

### 1. Cache discipline

Sessions with `cost_usd >= 5` and `cache_hit_pct < 70` (from
`sessions.csv`). If empty, say so explicitly: that means cache is
working everywhere it should.

### 2. Skill / MCP loader bloat

Reference the first-turn input table above. Above ~50K is suspicious;
flag the slugs for the user to investigate which plugins/MCPs/skills
are loading.

### 3. Subagent fan-out

High `subagent_count` matched by high `assistant_turns` is healthy
(genuine parallel work). High `subagent_cost` in short-turn sessions
suggests unproductive fan-out. Pull from the top sessions list.

### 4. Repeat tool patterns

The "SKILL/MEMORY CANDIDATES" section of summarize.py output. Tools
called in >50% of sessions and >1000 calls are skill/memory candidates
the user has not yet captured. Empty list = existing skills/memory are
absorbing what they should.

## Notable specific findings

Anything outlier-shaped that doesn't fit the above categories. Single
mega-sessions, fleet-sweep days, unusual model mixes, etc. Quote
specific dollar figures and session IDs.

## Methodology

- Walks `<projects>/<slug>/<sessionId>.jsonl` (parents) and
  `<projects>/<slug>/<sessionId>/subagents/agent-*.jsonl` (subagents).
- Dedupes assistant turns by `message.id` to avoid the snapshot
  double-count gotcha.
- Prices each turn per the canonical Anthropic rate table (Opus
  $5/$25, Sonnet $3/$15, Haiku $1/$5; cache read 0.1×, cache write
  1.25× input rate; rates doubled when `model.id` contains `[1m]`).
- Filters by first-entry timestamp into [start, end+1) UTC.
- Re-runnable: `python scripts/analyze-month.py <projects> --month YYYY-MM`
  then `python scripts/summarize.py [--paid <usd>]`.
