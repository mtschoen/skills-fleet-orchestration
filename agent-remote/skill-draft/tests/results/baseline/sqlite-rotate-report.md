# Baseline result: sqlite-rotate (the rich one)

**Scenario:** `scenario-sqlite-rotate.md`
**Phase:** RED
**Outcome:** **Fully completed end-to-end via raw ssh.** Including real
install on remote-host, real verification (timer scheduled + service fired +
backup file created + journald lines visible), and complete clean teardown.
28 tool calls, ~6 minutes wall time.

## Why this result is important

It demonstrates that a competent agent **can** do stateful multi-step
remote Linux work from a Windows host using only raw ssh, when:

1. The task framing explicitly forbids unverified deliverables.
2. The agent happens to reach for absolute-path commands first (so it
   doesn't hit the `cd`-outside-project permission wall).
3. The task is linear enough that errors don't require tight iteration.

This **undercuts** the "agents can't do remote linux work" value prop I
was assuming when we started. It does NOT undercut the efficiency +
iteration-scaling + framing-consistency value prop. See "What this means
for the skill" below.

## What the agent produced

All in `C:\Users\user\skills-dev\test-sandbox\worktrees\sqlite-rotate-baseline\`
(since deleted as part of baseline cleanup):

- `src/myrepo/core/backup.py` (~180 lines) — rotation logic,
  `rotate_backup()` + `prune_old_backups()`, module-level `main()` so
  `python -m myrepo.core.backup` is the systemd ExecStart.
- `ops/systemd/myrepo-db-rotate.service` — Type=oneshot user unit.
- `ops/systemd/myrepo-db-rotate.timer` — `OnCalendar=*-*-* 03:00:00`.
- `ops/systemd/README.md` — install/uninstall, mentions `loginctl enable-linger`.
- `ops/systemd/install.py` (~115 lines) — cross-platform installer,
  no-ops cleanly on Windows/macOS.
- `tests/test_backup.py` — 14 tests, 100% statement coverage on
  `backup.py` (92 statements).
- `tests/test_systemd_installer.py` — 9 tests, loads the installer
  via `importlib.util` since it lives outside `src/`.

Local `pytest tests/test_backup.py tests/test_systemd_installer.py`: **22 passed**.

## Friction captured (the good stuff)

### 1. scp denied by harness → stdin-redirect workaround

The agent's instinct was `scp src/myrepo/core/backup.py user@remote-host:...`.
That was denied. Its workaround was clever:

```bash
ssh user@remote-host 'cat > /home/user/myrepo/src/myrepo/core/backup.py' < local/backup.py
```

Stdin redirect avoids heredoc quoting hell entirely — no `$VAR` expansion
issues, no escaping backticks, no EOF-in-content problems. **The skill
should document this pattern as a thing raw-ssh users discover the hard
way, and as something the wrapper eliminates by writing files directly
inside the remote worktree.**

### 2. venv assumption wrong → one round-trip to probe + fix

The agent initially hardcoded `%h/myrepo/.venv/bin/python` in the service
unit. Probe revealed no venv on remote-host; myrepo is installed editable
into system site-packages (`/home/user/myrepo/src/myrepo/__init__.py`).
One edit to fix.

**Skill implication:** the wrapper's remote execution environment should
be set up once (e.g. via a remote-side bootstrap script installed during
first use) so every invocation doesn't re-probe for venv/python/PATH.

### 3. `Linger=no` → deliberate documented skip

`systemctl --user` on remote-host only works while user has an active
session. The agent correctly identified that persistent scheduling would
need `sudo loginctl enable-linger user`, didn't have sudo, and chose
to document the requirement in the README rather than try to escalate.
Good judgment.

### 4. systemctl exit code 3 for inactive units

`systemctl status` returns 3 when a unit is inactive. The agent's bash
call exited with 3 "because systemctl status exited 3" — the agent
correctly recognized this as not a real failure. Minor but shows
awareness of the non-obvious exit code semantics.

### 5. Service vs timer enable state

Status output showed `Loaded: ...; disabled; preset: enabled` on the
service unit. The agent correctly diagnosed: "only the timer is enabled
in `timers.target.wants/`; the service is fired by the timer, not enabled
standalone." Brief consideration of "did enable --now fail?" then
confirmed via symlink output that it didn't.

## Teardown

Final state probe (verbatim):
```
=== timers ===
none
=== unit files ===
none
=== backups dir ===
ls: cannot access '/home/user/.myrepo/backups': No such file or directory
absent
=== backup.py ===
ls: cannot access '/home/user/myrepo/src/myrepo/core/backup.py': No such file or directory
absent
```

**Zero residue on remote-host.** The agent deleted everything it installed,
including the code file it pushed into user's myrepo checkout.

## What this means for the skill

**Value prop, repositioned:**

Raw-ssh orchestration is not impossible — it's just the equivalent of a
human typing `ssh host 'cmd1' && ssh host 'cmd2' && ssh host 'cat > file' < local`
for every step. Works, but nobody does it that way when they have a choice.
The skill gives agents the "open a terminal" affordance: spawn `claude -p`
on the remote, hand it the task, let it work in a warm shell where the
environment is loaded once and iteration is natural.

**Specific things the wrapper should handle so agents don't re-derive them:**

1. File transfer to the remote worktree (no scp-denial workaround needed).
2. Python/venv/PATH discovery on the remote (one-time bootstrap, cached).
3. Default working directory = a fresh worktree, not the user's live checkout.
4. Permission mode for the spawned `claude -p` (acceptEdits default, the
   wrapper seeds a narrow settings.local.json into the worktree).
5. Structured result capture: branch, commit, files_changed, journald
   excerpts — instead of the caller parsing `git status` over ssh.
6. Clean teardown via a `cleanup` subcommand that removes the worktree
   and any remote-side state.

**Framing the skill needs to encode (per disk-throughput + gpu-bandwidth
reports):** the SKILL.md's trigger section must name silent drift as the
failure mode the skill exists to prevent, in the exact words agents use
when they're about to drift. Both bailed agents cited the framing as the
reason they resisted — encoding it once in the skill means every caller
gets the framing for free.
