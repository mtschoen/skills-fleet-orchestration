# cost-estimator

A Claude Code skill that prices session JSONLs from local transcripts.
Two halves planned:

- **Retrospective — built (2026-05-04).** "What did I spend over [date
  range]?" Walks `~/.claude/projects` (and equivalent on other hosts),
  dedupes assistant turns by `message.id`, prices each turn per the
  canonical Anthropic rate table, and reports per-session, daily, and
  waste-pattern breakdowns. Skill body in `skill-draft/SKILL.md`,
  scripts in `scripts/`.
- **Predictive — planned.** "How much will it cost to [some future
  task]?" Uses Anthropic's `count_tokens` API + heuristics + the
  retrospective dataset as a reference. Design notes below.

## Files

- `skill-draft/SKILL.md` — the retrospective skill (the working part).
- `scripts/analyze-month.py` — JSONL walker + per-turn pricer.
- `scripts/summarize.py` — CSV reader + waste-pattern report.
- `reports/` — gitignored save location for synthesized reports.
- `.gitignore` — keeps reports and CSV outputs out of git.

## Predictive companion (planned)

The originating user goal: get a defensible cost estimate **before**
invoking Claude on a task. Concrete shapes:

- "How much would it cost to summarize these 50 files?"
- "If I let an agent loop on this codebase for 8 hours, what's that cost?"
- "What does it cost to add this 3KB system prompt to every turn?"
- "How much to implement this plan?" (the abstract one)

### Build path

A pragmatic v1 → v2 split, tightest first.

**v1 — bounded subcases (math is exact).** All three are deterministic
given input tokens and a turn count:

- "Cost to summarize N files" → `count_tokens` on file contents, pick a
  model, fixed output estimate (~200–500 tokens), arithmetic.
- "Cost to add a 5KB system prompt to every turn for K turns" →
  `count_tokens` once, multiply by K, apply cache-write/read split.
- "Cost of an agent loop for K iterations of T turns each" → same shape.

**v2 — fuzzy plan estimation (needs heuristics).** Two plausible
foundations:

1. **LLM-based turn-count estimator.** Show the plan to Claude, ask
   "how many turns?" Brittle but usable for first-cut bounds.
2. **Regression on the historical dataset.** The retrospective half
   produced a `sessions.csv` with hundreds of labeled rows (cost,
   turns, top tools, models, subagents). If the user labels a sample
   by task profile — "refactor", "debug", "feature build",
   "exploration" — that becomes training input for a per-profile
   $/turn estimator.

v2 should report ranges, not point estimates, and explicitly call out
the assumption that drove the bounds.

### Name-collision notes

Two built-in slash commands already exist in Claude Code that this skill
does **not** want to collide with:

- `/cost` — current-session per-model breakdown (Claude Code v2.1.92+).
- `/cost-estimate` — scans a codebase to compute what it would have cost
  a human team to build it. Different purpose entirely.

The retrospective half cross-validates against `ryoppippi/ccusage`
(<https://github.com/ryoppippi/ccusage>) as a sanity check; that's the
only third-party tool the skill body references.

### Technical primitive — `count_tokens` API

- Docs: <https://docs.anthropic.com/en/docs/build-with-claude/token-counting>
- Free to use, subject to RPM rate limits per usage tier.
- Returns the exact input token count for any messages array.
- Note: the count "should be considered an estimate" — actual billing
  may differ slightly due to system-added tokens (orchestration
  overhead, not billed).

**Auth concern unresolved.** The user's `~/.claude/.credentials.json`
holds an OAuth Bearer used for the subscription path. Works for the
undocumented `/api/oauth/usage` endpoint (with `anthropic-beta:
oauth-2025-04-20`). Unknown whether it works for `count_tokens`. First
job for the predictive build is to probe it:

```bash
TOKEN=$(python3 -c "import json,os; print(json.load(open(os.path.expanduser('~/.claude/.credentials.json')))['claudeAiOauth']['accessToken'])")
curl -s https://api.anthropic.com/v1/messages/count_tokens \
  -H "Authorization: Bearer $TOKEN" \
  -H "anthropic-beta: oauth-2025-04-20" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-opus-4-7","messages":[{"role":"user","content":"hello"}]}'
```

200 with `{"input_tokens": N}` → OAuth works. 401/403 → fall back to
Console API key (`ANTHROPIC_API_KEY` env var); document that the
predictive half requires a separate API key.

### Test cases for the predictive skill

End-to-end validation when v1 lands:

- "How much to summarize the files in `src/components/`?" → reads files,
  counts tokens, estimates output ≈ 200 tokens, multiplies.
- "How much for an agent that reads 10 docs and writes 1 page of
  analysis?" → mid-range estimate with explicit assumptions.
- "Cost of adding a 5KB system prompt to every turn for the rest of a
  session expected to be 100 turns long?" → repeat-input arithmetic
  with cache-write/read modeling.

### Build conventions for v1

The skill should:

- Trigger on phrases like "how much will it cost", "estimate cost",
  "predict spend", "what would XYZ cost", "cost projection".
- Call `count_tokens` on actual content (files, draft prompts) — don't
  use char/4 heuristics.
- Heuristic-estimate output tokens by task type (code edit ≈ N tokens,
  summary ≈ M, agent-loop iteration ≈ K). Bound uncertainty
  explicitly: "between $X and $Y".
- Pin the pricing table inline (don't depend on memory notes — skill
  should stay self-contained, eventually publishable).
- Honor the cache-write/read multipliers and the Opus 1M-context tier
  doubling.
- Present output as a breakdown: input cost + output cost + cache
  savings (if applicable) + total range.
