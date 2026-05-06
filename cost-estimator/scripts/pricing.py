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
