"""Canonical pricing helpers shared across cost-estimator scripts.

Single source of truth for the per-MTok rates and cache multipliers.
Both analyze-month.py (retrospective bulk analysis) and plot-session.py
(single-session trajectory) import from here so the formula does not
drift.

The PRICES table below is the source of truth for these scripts;
SKILL.md's pricing table mirrors it. Keep the two in sync when rates
change.
"""

from __future__ import annotations

from datetime import datetime


# Per-MTok rates (verified 2026-04 against Anthropic docs; fable/sonnet5
# rows added 2026-07-16, verified against the live pricing page same day).
# One flat rate per model for all time -- no time-windowed pricing. An
# earlier revision modeled a temporary Sonnet 5 introductory rate that
# would go stale on a fixed end date; that concept was removed in favor
# of this simplifying assumption.
PRICES = {
    "fable":   (10.0, 50.0),
    "sonnet5": (3.0, 15.0),
    "opus":    (5.0, 25.0),
    "sonnet":  (3.0, 15.0),
    "haiku":   (1.0, 5.0),
}
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def rates_for(family):
    """Per-MTok (input, output) rates for a model family."""
    return PRICES[family]


def model_family(model_identifier):
    if not model_identifier:
        return None
    name = model_identifier.lower()
    if "fable" in name or "mythos" in name:
        return "fable"
    if "opus" in name:
        return "opus"
    # sonnet-5 before the generic sonnet match: distinct intro rate card.
    if "sonnet-5" in name:
        return "sonnet5"
    if "sonnet" in name:
        return "sonnet"
    if "haiku" in name:
        return "haiku"
    return None


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
    input_rate, output_rate = rates_for(family)
    # The 1M-context tier (`[1m]` model ids) bills at the SAME flat per-token
    # rate -- no surcharge above 200K, verified 2026-06 against ~/.claude.json
    # billing across 28 Opus[1m] sessions and current Anthropic docs.
    return (input_tokens * input_rate
            + output_tokens * output_rate
            + cache_read_tokens * input_rate * CACHE_READ_MULTIPLIER
            + cache_write_tokens * input_rate * CACHE_WRITE_MULTIPLIER) / 1_000_000


def unpriced_usage(model_identifier, input_tokens, output_tokens,
                   cache_read_tokens, cache_write_tokens):
    """Flag a turn that cost_for_turn() silently priced at $0.00.

    Returns (turns=1, tokens) when `model_identifier` is a real (non-empty)
    id that model_family() doesn't recognize -- the exact condition that
    makes cost_for_turn() return 0.0 above. Returns None for a known
    family, a missing/empty model id (a different, unrelated gap), or a
    turn with zero total token volume. The zero-volume exclusion covers
    "<synthetic>" transcript entries generically: Claude Code emits them
    with an unrecognized model id but all-zero usage, so without this
    check every real report would falsely raise the UNPRICED MODELS
    warning even though nothing was actually undercounted.
    `tokens` is this turn's full volume (input + output + cache read +
    cache write), so callers can judge how much a silent gap matters.

    Callers accumulate this per model id into a running {turns, tokens}
    tally and surface it loudly -- a new model family priced at $0.00
    would otherwise undercount every retrospective report without any
    warning.
    """
    if not model_identifier or model_family(model_identifier) is not None:
        return None
    tokens = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
    if tokens == 0:
        return None
    return 1, tokens


try:
    from orjson import loads as _loads
except ImportError:
    from json import loads as _loads


def iter_assistant_turns(jsonl_path):
    """Yield one record per priced assistant turn in a Claude Code JSONL.

    Dedupes on `message.id` (turns recur in JSONL snapshots; naive
    iteration double-counts). Turns without a `message.id` are kept.
    Lines that fail JSON parsing are silently skipped.

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
            if not isinstance(entry, dict):
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
