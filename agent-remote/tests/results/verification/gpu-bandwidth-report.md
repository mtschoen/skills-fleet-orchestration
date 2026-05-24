# Verification result: gpu-bandwidth

**Scenario:** `scenario-gpu-bandwidth.md`
**Phase:** GREEN
**Outcome:** ✅ Real bandwidth matrix produced from remote-host's 4 GPUs. ❌ `new_commit`/`files_changed` reported as null/empty even though the remote committed (real bug). ❌ No way to pull remote-authored code back locally — agent re-implemented same file in parallel.

## Key data points

- **Actually built nvbandwidth from source on remote-host** inside ONE `remote-claude run` call. cmake + boost + CUDA dep loop, build, run, parse, commit — all in a single session. Local agent never touched apt-get or build errors. **This is the iteration-scaling value prop concretely demonstrated.**
- **Real bandwidth matrix from remote-host:**

  ```text
  RTX 4090 + 3x RTX 2080 Ti
  h2d: 6.03  6.12  6.12  6.10  GB/s
  d2h: 6.61  6.61  6.61  6.61  GB/s
  d2d: waived (consumer GPUs, no NVLink, PCIe P2P disabled)
  ```

- **Tool-call count:** 3 `remote-claude run` + 3 `remote-claude cleanup` + ~10 local Read/Edit/Write. Equivalent raw-ssh estimate from the agent: "significantly worse — cmake/cuda/boost dependency installation alone is usually 5-15 trial-and-error round trips."
- **Friction the wrapper hid:** ssh quoting/heredocs, MSYS path mangling, login-shell PATH for cmake/nvcc, worktree creation, permission seeding, working-directory state. None of it surfaced.

## Wrapper rough edges encountered

1. **🔴 `new_commit: null` and `files_changed: []` despite the remote committing.** Run 1 reported no commit was created. Run 2's `parent_commit` proved otherwise (`7df5d2634661…`). The wrapper's parser for "what changed" appears to miss commits made via nested skills/worktrees inside the remote `claude -p` session — possibly the commits land on a different ref than the worktree's HEAD that `collect_result()` checks. **Real bug, real impact.** A caller that trusts `files_changed` would assume nothing happened.
2. **🔴 No way to pull remote-authored code back to local.** Local sandbox blocks `git fetch` against arbitrary remotes. Only fallback was to ask the remote to `cat` the file back, which then hit `stdout_tail` truncation, so the agent **re-implemented the same file locally from scratch**. Same workflow bug as the other two verification runs. **Architectural gap, not a small fix — needs `--copy-back PATH:LOCAL_PATH` flag or a separate `fetch` subcommand.**
3. **`stdout_tail` mojibake.** Em-dashes come back as `\u00e2\u20ac\u201d`. Same encoding bug as disk-throughput verification.
4. **No-op runs spin up a fresh worktree.** Read-only "cat a file" runs incur the full worktree creation overhead. Wants a lightweight `exec` mode.
5. **`stdout_tail` truncation hides large prints.** Same bug as sqlite-rotate verification.

## What was implemented where

- **Local (live myrepo tree):** `nvbandwidth.py` runner+parser, `db.py` table additions + 4 helpers, `hardware.py` route additions, `hardware.html` UI card. **Polluted the live tree** because the verification agent worked from `cwd=myrepo` not from a worktree.
- **Remote (remote-host via wrapper):** Built nvbandwidth from source, ran all three benchmark passes against the 4 GPUs, wrote a server-side `nvbandwidth.py`, committed it as `7df5d26` on `remote-claude/gpu-bandwidth-verify`. Branch was cleaned up via the wrapper's cleanup subcommand.

**Two parallel implementations of `nvbandwidth.py` existed momentarily**, one local and one remote, both based on the same prompt spec, never merged. The remote one was thrown away with the worktree.
