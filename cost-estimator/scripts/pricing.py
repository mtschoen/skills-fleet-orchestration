"""Canonical pricing helpers shared across cost-estimator scripts.

Single source of truth for the per-MTok rates and cache multipliers.
Both analyze-month.py (retrospective bulk analysis) and plot-session.py
(single-session trajectory) import from here so the formula does not
drift.

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
    # The 1M-context tier (`[1m]` model ids) bills at the SAME flat per-token
    # rate -- no surcharge above 200K, verified 2026-06 against ~/.claude.json
    # billing across 28 Opus[1m] sessions and current Anthropic docs.
    return (input_tokens * input_rate
            + output_tokens * output_rate
            + cache_read_tokens * input_rate * CACHE_READ_MULTIPLIER
            + cache_write_tokens * input_rate * CACHE_WRITE_MULTIPLIER) / 1_000_000


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
