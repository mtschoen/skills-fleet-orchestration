# fleet-orchestration

A Claude Code skill for dispatching subagents across **multiple local project repositories** — feature implementation, maintenance sweeps, or fleet-wide investigation. Extends `superpowers:dispatching-parallel-agents` with the cross-repo governance that skill's single-codebase assumption doesn't cover.

## When it fires

Multi-repo subagent work: "spawn agents to fix X across all my projects", "run a maintenance pass", "work on tasks from several repos at once", or any use of projdash MCP tools (`list_projects`, `find_dirty`, `find_stale_maintenance`) to plan multi-repo work.

For fixing several bugs in **one** repo, use the parent skill alone.

## What it does

Adds task selection/triage across the fleet, a user pre-approval gate (feature mode), result triage (the orchestrator answers agents' open questions rather than forwarding them verbatim), the maintenance-vs-feature dual mode, `.maintenance.json` breadcrumbs, and cross-repo permission/worktree-isolation guidance.

The authoritative spec is [`SKILL.md`](SKILL.md).

**Repo:** <https://github.com/mtschoen/skills-fleet-orchestration>
