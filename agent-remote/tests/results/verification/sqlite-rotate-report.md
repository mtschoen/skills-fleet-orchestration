# Verification result: sqlite-rotate

**Scenario:** `scenario-sqlite-rotate.md`
**Phase:** GREEN
**Outcome:** ✅ Wrapper worked first-try with no bugs in mechanics. ✅ 9× tool-call reduction vs baseline (3 vs 28). ❌ `stdout_tail` truncation defeated the "paste verification output" requirement. ❌ Workflow split-brain (parallel local + remote implementations of the same files).

## Key data points

- **Direct comparison to baseline:** baseline run took **28 tool calls + ~6 minutes** to install, verify, tear down the systemd timer via raw ssh. Verification run took **3 tool calls** (1 `run` + 1 `cleanup` + 1 independent ssh probe). **~9× reduction** for the remote half.
- **Wrapper mechanics worked first-try:** *"ssh, MSYS path handling, login-shell wrapping, and permission seeding all worked first-try. Rough edges above are about observability, not correctness."*
- **Independent post-run verification confirmed clean teardown** on remote-host:

  ```text
  systemctl --user list-unit-files | grep myrepo    → empty
  ls ~/.config/systemd/user/ | grep myrepo           → empty
  ls ~/.myrepo/backups/                              → directory does not exist
  ```

## Wrapper rough edges encountered

1. **🔴 `stdout_tail` is too short for verification reporting.** The remote agent ran ~8 distinct verification commands (`systemctl list-timers`, `journalctl`, `ls -lh backup`, etc.) producing meaningful output. The wrapper kept only the final summary sentence. For tasks where the deliverable IS *"paste the real verification output"*, this defeats the point. Agent had to fall back to an independent post-hoc ssh probe to confirm cleanup.
2. **`files_changed` includes files the prompt didn't ask for.** `PLAN.md` showed up in `files_changed` even though the prompt was scoped to install/verify/teardown - remote agent likely auto-invoked a planning skill. Diff base may be too wide.
3. **No streaming output.** A 600s task is opaque until it returns.
4. **`cleanup` is a separate manual call.** Easy to forget. Wants `--auto-cleanup` flag for "verify and discard" cases.
5. **No bugs in correctness** - only ergonomics/observability.

## What was implemented where

- **Local (live myrepo tree):** `db_rotate.py` rotation logic + 8 unit tests at 100% coverage, `ops/systemd/myrepo-db-rotate.{service,timer}`, `ops/systemd/install.py` cross-platform installer, `ops/systemd/README.md`. All written into `C:\Users\user\myrepo\` (live tree, not a worktree).
- **Remote (remote-host via wrapper):** Per the wrapper's `files_changed` JSON, the same 5 files appeared on the remote branch - but the agent's report confused itself about how that happened. Most likely explanation: the remote `claude -p` session re-implemented them from scratch based on the prompt content, since the wrapper does not push local changes to the remote. Two parallel implementations existed momentarily.

## Workflow gotcha (also seen in disk-throughput and gpu-bandwidth verifications)

Same architectural gap: **the wrapper has no story for code flowing local ↔ remote within a single skill invocation.** Three verification agents, three independent rediscoveries of "I have to write the file twice" because the remote starts from the remote's HEAD, not from local working state, and there's no `--push-first` or `--fetch-back` mechanism. SKILL.md needs to clearly document this boundary, and the wrapper probably needs flags for both directions.
