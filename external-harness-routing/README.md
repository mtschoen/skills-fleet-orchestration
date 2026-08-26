# external-harness-routing

A skill that teaches an agent to divert work from its own metered harness to other installed agent CLIs - conserving the scarce subscription pool and reaching models that exist in only one place.

## When it fires

The orchestrator's pool is the constrained resource and a lane does not need it: "run this on a cheaper harness", "save my Claude tokens", "use another subscription for this sweep", fan-out jobs where built-in subagents would burn the scarce pool, or any time the agent is about to hand-roll headless CLI calls to claude, codex, gemini, agy, opencode, kimi, qwen, or pi.

## What it does

Three steps: inventory which agent CLIs are installed and authenticated (with cheap probes and the silent-quota-exhaustion trap), pick the lane by capability tier instead of model name (orchestrator seat keeps judgment work; mid-tier is the implementation default; explicit model on every dispatch), and dispatch headlessly with the fleet-proven pattern - prompt file, tracked background run with a hard timeout, report file as the return channel, absolute paths, and a mandatory "STOP and report BLOCKED" clause for missing inputs. Includes a per-harness cheat sheet, hung-dispatch detection, and an honest take on interactive diversion.

Companion skills: `agent-remote` (same idea across machines), `fleet-orchestration` (multi-repo dispatch and the fuller tier-routing rules), `superpowers:dispatching-parallel-agents` (built-in same-harness lanes).

The authoritative spec is [`SKILL.md`](SKILL.md).

**Repo:** <https://github.com/mtschoen/skills-external-harness-routing>
