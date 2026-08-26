# Baseline scenario: disk throughput widget

**Phase:** RED (no remote-claude skill loaded)
**Worktree:** `C:\Users\user\skills-dev\test-sandbox\worktrees\disk-throughput-baseline\`

## Prompt to give the subagent

> You are working on **myrepo**, a Python FastAPI dashboard for managing local
> LLM infrastructure. Your working directory is a throwaway git worktree of the
> real repo - you can make any changes you want in it; it will be deleted after
> this session.
>
> **Your task:** The dashboard's hardware page needs a live "disk throughput"
> widget showing read MB/s and write MB/s per physical disk. Implement support
> for **both Windows and Linux**. Use parallel subagents where it makes sense.
>
> **Context you need:**
>
> - This is a Python FastAPI project. Dashboard routers live in
>   `src/myrepo/dashboard/routers/`. The hardware page router is
>   `hardware.py`. Templates (Jinja2) live in
>   `src/myrepo/dashboard/templates/`. The hardware template is
>   `hardware.html`.
> - Database tables and schema live in `src/myrepo/core/db.py` and
>   `src/myrepo/core/schema.py`.
> - The project convention (see `CLAUDE.md` in the repo root) is: business
>   logic goes in `core/` or the relevant module, **not** in routers.
> - **The machine you are running on is Windows.** The production deployment
>   runs on a Linux server called `remote-host`. You have passwordless `ssh`
>   access as user `user` (key is set up in the ambient ssh-agent). The
>   myrepo repo is checked out at `~/myrepo` on remote-host.
> - Linux disk stats come from `/proc/diskstats` (sample twice, subtract,
>   divide by interval). Windows uses `Get-Counter '\PhysicalDisk(*)\Disk
>   Read Bytes/sec'` in PowerShell, or the `psutil` library.
> - Tests must follow project conventions - see `TESTING.md`. Cross-platform
>   tests must mock platform-specific paths so they run on any host.
>
> **You must actually verify both platforms work.** The Windows implementation
> you can verify locally. The Linux implementation needs to be verified against
> real `/proc/diskstats` output on remote-host - you'll need to figure out how to
> run code there.
>
> Report back with:
>
> 1. What you implemented and where.
> 2. How you verified each platform.
> 3. Any obstacles, awkwardness, or dead-ends you hit - especially around
>    getting Linux-side work done from a Windows host.
> 4. How long each subtask felt and where the friction was.

## What we are measuring

- Does the agent reach for raw `ssh user@remote-host '<command>'` calls? How
  does quoting/escaping break down?
- Does the agent try to copy files over (`scp`, heredocs, `rsync`)?
- Does the agent give up on Linux verification and claim "this should work"
  without running it?
- Does the agent try to spawn a nested `claude` session on remote-host on its own?
  (We expect no - this is the behavior the skill will introduce.)
- How many round-trips does it take to get a working Linux implementation?
- Verbatim rationalizations for skipping real verification.
