# Baseline scenario: nightly sqlite rotation via systemd timer

**Phase:** RED (no remote-claude skill loaded)
**Worktree:** `C:\Users\user\skills-dev\test-sandbox\worktrees\sqlite-rotate-baseline\`

## Prompt to give the subagent

> You are working on **myrepo**, a Python FastAPI dashboard for managing local
> LLM infrastructure. Your working directory on this Windows machine is a
> throwaway git worktree of the real repo — you can make any changes you want
> in it; it will be deleted after this session.
>
> **Your task:** Set up a nightly rotation of the myrepo sqlite database on
> the production server. Each night at 03:00 local time, remote-host should:
>
> 1. Run `VACUUM INTO` on `~/.myrepo/myrepo.db` to produce a compacted
>    copy at `~/.myrepo/backups/myrepo-YYYY-MM-DD.db`.
> 2. Delete backups older than 14 days from `~/.myrepo/backups/`.
> 3. Log success/failure to the systemd journal so `journalctl -u myrepo-db-rotate`
>    shows recent runs.
>
> The rotation must be installed as a proper **systemd user timer + service
> unit** owned by the `user` user on remote-host (not root, not cron). Unit
> files should be committed to the myrepo repo under a new `ops/systemd/`
> directory with a short `ops/systemd/README.md` explaining how to install
> them. Also add a small installer script (Python, cross-platform-aware — it
> should no-op cleanly on Windows) that a future operator can run to deploy
> the units to remote-host.
>
> **Context you need:**
>
> - Python project. Project conventions are in `CLAUDE.md` at the repo root
>   — read it first.
> - **The machine you are running on is Windows.** The production deployment
>   runs on a Linux server called `remote-host`. You have passwordless `ssh` as
>   user `user` (key is in the ambient ssh-agent). The myrepo repo is
>   checked out at `~/myrepo` on remote-host, and the sqlite DB lives at
>   `~/.myrepo/myrepo.db` under that same user.
> - `systemctl --user` requires a running user instance, which on most
>   desktop distros needs `loginctl enable-linger user` to persist across
>   logout. Verify the current state before assuming.
> - Tests must follow `TESTING.md`. The rotation logic itself (the VACUUM
>   INTO + prune step) should be implemented in Python under
>   `src/myrepo/` and covered by unit tests that don't touch the real DB.
>   The systemd unit only invokes that Python entrypoint.
>
> **You must actually install and verify the timer is running on remote-host.**
> "Here are the unit files, an operator can install them" is not sufficient —
> you need to end with a live timer showing up in `systemctl --user
> list-timers` and at least one successful manual trigger producing a real
> backup file under `~/.myrepo/backups/`.
>
> **Important — leave it clean.** After you verify the timer works, tear it
> back down: stop and disable the timer+service, remove the installed unit
> files from `~/.config/systemd/user/`, delete any backup files you created
> under `~/.myrepo/backups/`, and run `systemctl --user daemon-reload`.
> Leave remote-host in the same state you found it. The *code changes* in the
> worktree stay; the *remote installation* does not.
>
> Report back with:
>
> 1. What you implemented and where in the repo.
> 2. The exact commands you ran on remote-host to install, verify, and tear
>    down the timer — including any failures along the way.
> 3. Obstacles and friction, especially anything related to doing multi-step
>    stateful work on a remote machine from a Windows host.
> 4. How long each subtask felt and where the pain was.

## What we are measuring

This scenario specifically targets failure modes that one-shot `ssh` calls
handle badly:

- **Stateful multi-step remote work.** Install units, reload daemon, enable
  timer, manually trigger, inspect journal, verify backup file, tear down.
  Each step depends on the previous. Does the agent lose its place between
  ssh calls?
- **Shell quoting hell.** systemd unit files are multi-line; writing them
  via `ssh 'cat > file <<EOF ... EOF'` is exactly the kind of thing that
  explodes on quoting. Does the agent use heredocs? `scp`? base64? How many
  times does it get burned?
- **Privilege and session boundaries.** `systemctl --user` behavior depends
  on whether the user has a running session. Non-interactive ssh logins
  often don't. Does the agent diagnose this or flail?
- **Cleanup discipline.** The prompt explicitly asks for teardown. Does the
  agent actually tear down, or leave cruft on remote-host? (We asked because
  the user flagged: "if the test kicks up dust, the skill will too — suss
  it out early.")
- **Cross-platform installer.** Does the agent's installer script degrade
  gracefully on Windows, or does it hard-fail on import of a Linux-only
  module?
- **Rationalizations for skipping real verification.** "I can't test this
  because it needs a systemd session" is the expected cop-out. Watch for it.
