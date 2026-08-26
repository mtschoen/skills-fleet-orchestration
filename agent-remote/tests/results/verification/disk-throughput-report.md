# Verification result: disk-throughput

**Scenario:** `scenario-disk-throughput.md`
**Phase:** GREEN
**Outcome:** ✅ Wrapper worked. Single `run` call did real `/proc/diskstats` verification on remote-host via real `dd` workload. ❌ `cleanup` subcommand hung indefinitely; agent had to fall back to manual ssh.

## Key data points

- **One `agent-remote run` invocation** for the entire Linux verification half. Replaces the 10-15 raw-ssh calls that would have been needed for: git worktree add, scp/edit file, python -c one-liner, dd workload, sampler, diff, git add/commit.
- **Real verification on real data:** the remote session pasted real `/proc/diskstats` output AND ran a real `dd if=/dev/zero of=/home/user/disktest bs=1M count=200 conv=fdatasync` workload AND confirmed sector math: 200.1 MB writes detected vs 200 MB target. Discovered and corrected a tmpfs gotcha along the way.
- **Tool-call count:** ~20 total (research + edits + smoke test + 1 run + polling + cleanup + report). Roughly **1 of those was the wrapper run** that did the work of 10-15 ssh calls.
- **`new_commit` and `files_changed` populated correctly this time:** `aef9f7a4445857f2da7c29e65ac0c927238f3967` + `["src/myrepo/core/disk_io.py"]`. So the gpu-bandwidth `new_commit:null` bug is NOT universal - it's tied to specific remote agent behavior (probably nested skills).

## Wrapper rough edges encountered

1. **🔴 `cleanup` subcommand hangs indefinitely.** Wait > 60s, output file 0 bytes, worktree/branch still on the remote. Agent worked around with manual `ssh ... git worktree remove --force && git branch -D`. **Real bug - needs fix.** Likely cause: subprocess stdin not closed, ssh waiting on inherited stdin in non-TTY context.
2. **Parent commit drift is silent.** Remote worktree starts from remote `main` HEAD, not from local working state. Local uncommitted changes are invisible to the remote session. Worked fine for this verification task but would silently break "extend the file I just wrote locally" workflows. Wrapper should warn loudly.
3. **Background-only invocation on Windows wastes polling calls.** ~4 tool calls wasted on `sleep && wc -l` waiting for the run to finish. A built-in `--wait` mode wouldn't help here (the issue is *the orchestrator* having to poll a backgrounded run); might want a streaming mode instead.
4. **`stdout_tail` mojibake.** Em-dashes in the remote agent's prose come back as `\u00e2\u20ac\u201d`. UTF-8 → Latin-1 → JSON-escape encoding bug.
5. **No bug:** narrow per-worktree permission seeding worked - remote agent ran python + dd + git commit with no sudo/permission issues.

## Workflow gotcha (also seen in sqlite-rotate verification)

The agent wrote `disk_io.py` LOCALLY (in the live myrepo tree) AND the remote agent independently re-implemented `disk_io.py` from scratch on its branch. Two parallel implementations of the same file. The local copy is the canonical one for the dashboard router; the remote copy was thrown away with the worktree. Both agents observed: the remote starts from the remote's `main` HEAD, not from local state - so if you write code locally and then ask the remote to verify it, the remote won't see your local changes unless you `git push` first.

**This is the architectural gap I missed when designing the wrapper:** there's no story for code flowing between local ↔ remote inside a single skill invocation. The wrapper's intended use case is "delegate a self-contained task that produces a textual deliverable." For tasks where the deliverable is *code*, the agent has to either (a) accept duplicate parallel implementations or (b) `git push` first and `git fetch` after, both of which the skill should document but currently doesn't.
