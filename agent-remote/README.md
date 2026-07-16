# agent-remote

A skill (and supporting wrapper script) that lets an agent orchestrator
delegate work to an agent session (claude, opencode, or agy) running on a remote machine, inside an
isolated git worktree, returning structured results.

## Why

When working on cross-platform projects from a primary dev machine, some tasks
require executing code on a different OS — typically Linux for `/proc`, GPU
probing, systemd, or services that only run on the deployment host. The status
quo is for the orchestrator to pipe each command over `ssh`, which is awkward,
error-prone (shell quoting), and produces no persistent worker context between
calls.

This skill replaces that pattern with: "spawn an agent on the remote
host, give it the task, let it work in its own git worktree, collect its
report."

## Layout

```text
agent-remote/
  README.md                      # this file
  SKILL.md                       # the skill itself
  references/
    agent-remote.py              # the wrapper script
  tests/
    baseline/                    # RED-phase scenario prompts (no skill)
    results/                     # captured subagent transcripts
```

## Test plan (TDD-for-skills)

1. **RED:** Run baseline scenarios *without* the skill loaded. Capture how
   subagents naturally try (and struggle) to do remote work. Document
   rationalizations and pain points verbatim.
2. **GREEN:** Write `agent-remote.py` and `SKILL.md` to address those specific
   failure modes.
3. **REFACTOR:** Re-run scenarios *with* the skill. If subagents still misuse
   the wrapper or reach for raw ssh, close the loophole and re-test.

See `tests/baseline/` for the scenarios.

