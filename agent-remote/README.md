# remote-claude

A skill (and supporting wrapper script) that lets a Claude Code orchestrator
delegate work to a `claude -p` session running on a remote machine, inside an
isolated git worktree, returning structured results.

## Why

When working on cross-platform projects from a primary dev machine, some tasks
require executing code on a different OS — typically Linux for `/proc`, GPU
probing, systemd, or services that only run on the deployment host. The status
quo is for the orchestrator to pipe each command over `ssh`, which is awkward,
error-prone (shell quoting), and produces no persistent worker context between
calls.

This skill replaces that pattern with: "spawn a `claude -p` agent on the remote
host, give it the task, let it work in its own git worktree, collect its
report."

## Layout

```text
remote-claude/
  README.md                      # this file
  skill-draft/
    SKILL.md                     # the skill itself (drafted after baseline)
    references/
      remote-claude.py           # the wrapper script (drafted after baseline)
    tests/
      baseline/                  # RED-phase scenario prompts (no skill)
      verification/              # GREEN-phase scenario prompts (with skill)
      results/                   # captured subagent transcripts
```

## Test plan (TDD-for-skills)

1. **RED:** Run baseline scenarios *without* the skill loaded. Capture how
   subagents naturally try (and struggle) to do remote work. Document
   rationalizations and pain points verbatim.
2. **GREEN:** Write `remote-claude.py` and `SKILL.md` to address those specific
   failure modes.
3. **REFACTOR:** Re-run scenarios *with* the skill. If subagents still misuse
   the wrapper or reach for raw ssh, close the loophole and re-test.

See `skill-draft/tests/baseline/` for the scenarios.
