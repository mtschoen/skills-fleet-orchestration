#!/usr/bin/env python3
"""
agent-remote.py — spawn an agent session (claude, opencode, or agy) on a remote host
to do work in an isolated git worktree, capture a structured result, return.

The "open a terminal" affordance for agent orchestrators: instead of piping
each command over ssh, hand a task to a remote agent session running
in its own warm shell with persistent context.

Usage:
    agent-remote.py run \
        --host user@remote-host \
        --repo-path ~/myrepo \
        --prompt "Build nvbandwidth, run it against all GPUs, report the matrix." \
        [--branch agent-remote/nvbw-2026-04-07] \
        [--permission-mode acceptEdits] \
        [--agent opencode] \
        [--model ollama/qwen3.5-9b]

    agent-remote.py cleanup \
        --host user@remote-host \
        --branch agent-remote/nvbw-2026-04-07 \
        --repo-path ~/myrepo

    agent-remote.py probe \
        --host user@remote-host \
        --repo-path ~/myrepo

`run` returns a JSON result on stdout with:
    host, branch, worktree_path, parent_commit, new_commit (or null),
    files_changed, agent_exit_code, claude_exit_code, stdout_tail, stderr_tail,
    cleanup_command

Environment variables:
    REMOTE_AGENT_ALLOW_BYPASS=1   Allow --permission-mode bypassPermissions
                                  (otherwise that mode is refused)
    REMOTE_AGENT_TIMEOUT=3600     Max seconds for the remote agent run
                                  (default 3600)
"""

from __future__ import annotations

import argparse
import json
import os

# CRITICAL: must run before any subprocess imports/usage so the child env
# inherits the override. On Windows + Git Bash / MSYS, ssh.exe's argv is
# preprocessed to convert any /foo/bar argument into C:/Program Files/Git/foo/bar,
# mangling every absolute remote path. Setting these env vars on os.environ
# (rather than just in subprocess.run's env=) ensures the override sticks
# across the Python → ssh.exe boundary regardless of how subprocess builds
# the child env block on Windows.
os.environ.setdefault("MSYS_NO_PATHCONV", "1")
os.environ.setdefault("MSYS2_ARG_CONV_EXCL", "*")

import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Narrow allowlist written into the REMOTE worktree's .claude/settings.local.json
# before launching `claude -p`. This is what gives the spawned session its
# permissions without needing --permission-mode bypassPermissions.
#
# Narrow by tool *count*, not by what "Bash" can do (see the per-entry note
# below): anything the remote session needs that isn't in this list will
# still prompt, but claude -p is non-interactive, so prompts become denials.
# If a task needs something unusual (sudo, network tools, etc.), the CALLER
# should widen this via --extra-allow "Bash(sudo *)" etc.
# --------------------------------------------------------------------------
DEFAULT_REMOTE_ALLOWLIST: list[str] = [
    "Bash",  # full Bash - trust model assumes `host` is the user's own
    # machine. The worktree isolates the checkout/branch, not the OS: it does
    # not sandbox the filesystem, so this Bash entry can still read ~/.ssh,
    # exfiltrate data, or rm -rf anything the ssh user can reach. Don't point
    # this at a host you don't already trust with full shell access. To
    # narrow it, edit this list (e.g. swap "Bash" for specific
    # `Bash(cmd *)` patterns) - there's no CLI flag to shrink it, only
    # --extra-allow to widen it.
    "Read",
    "Edit",
    "Write",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
]


@dataclass
class RunResult:
    host: str
    branch: str
    worktree_path: str
    parent_commit: str
    new_commit: str | None
    files_changed: list[str]
    agent_exit_code: int
    stdout_tail: str
    stderr_tail: str
    cleanup_command: str
    success: bool = field(init=False)

    def __post_init__(self) -> None:
        self.success = self.agent_exit_code == 0

    def to_json(self) -> str:
        payload = {
            "success": self.success,
            "host": self.host,
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "parent_commit": self.parent_commit,
            "new_commit": self.new_commit,
            "files_changed": self.files_changed,
            "agent_exit_code": self.agent_exit_code,
            "claude_exit_code": self.agent_exit_code,  # backwards compatibility
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "cleanup_command": self.cleanup_command,
        }
        return json.dumps(payload, indent=2)


# --------------------------------------------------------------------------
# ssh helpers
# --------------------------------------------------------------------------


#: PATH prefix injected before every remote command. Ensures user-local
#: install dirs (~/.local/bin, ~/.npm-global/bin, ~/bin) are reachable
#: from non-interactive ssh sessions, where many distros' login shells
#: leave them off PATH. Without this, `claude`, `opencode`, `agy`, `pipx`-installed
#: tools, and a lot of npm-global binaries are mysteriously "not found."
REMOTE_PATH_PREFIX = "$HOME/.local/bin:$HOME/.npm-global/bin:$HOME/bin"


def rpath(p: str) -> str:
    """
    Convert a POSIX absolute path so it survives MSYS argv processing on
    Windows. MSYS-built executables (Git Bash's ssh.exe, git.exe) auto-
    convert any /foo/bar argument into C:/Program Files/Git/foo/bar. They
    skip paths starting with `//`. POSIX systems collapse leading `//` to
    `/`, so on the REMOTE side `//home/x` and `/home/x` are the same path.

    Setting MSYS_NO_PATHCONV=1 / MSYS2_ARG_CONV_EXCL=* in the env does NOT
    reliably catch this when the absolute path is embedded inside a string
    arg passed to ssh — only path-shaped argv elements are guarded. The
    only robust workaround is to mangle the path itself.

    No-op on Linux/macOS.
    """
    if sys.platform == "win32" and p.startswith("/") and not p.startswith("//"):
        return "/" + p
    return p


def qrp(p: str) -> str:
    """Shorthand: quote a remote path for embedding in a shell command,
    after applying the MSYS-safe path mangling. Always use this instead of
    bare shlex.quote() for remote filesystem paths."""
    return shlex.quote(rpath(p))


#: Common Git for Windows install prefixes that MSYS prepends to converted
#: POSIX paths. Order matters; check longest first.
_MSYS_PREFIXES = [
    "C:/Program Files/Git",
    "C:\\Program Files\\Git",
    "C:/Program Files (x86)/Git",
    "C:\\Program Files (x86)\\Git",
]


def unmangle_msys_path(p: str) -> str:
    """
    Reverse Git Bash's outbound argv path mangling. When a user runs
    `python agent-remote.py --repo-path /home/user/myrepo` from Git
    Bash on Windows, MSYS rewrites `/home/user/myrepo` into
    `C:/Program Files/Git/home/user/myrepo` BEFORE python.exe sees
    its argv. Python has no way to recover the original string from its
    own environment, so we detect the well-known Git install prefix and
    strip it.

    Workarounds the user can also use:
      - export MSYS_NO_PATHCONV=1 in the shell, or
      - pass paths with a leading double-slash (//home/user/myrepo),
        which MSYS leaves alone.

    No-op on non-Windows or paths that don't look mangled.
    """
    if sys.platform != "win32":
        return p
    for prefix in _MSYS_PREFIXES:
        if p.startswith(prefix + "/") or p.startswith(prefix + "\\"):
            tail = p[len(prefix) :].replace("\\", "/")
            # tail starts with /, which is what we want for a POSIX path
            return tail
    return p


def ssh_run(
    host: str,
    remote_command: str,
    *,
    input_text: str | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess:
    """
    Run a single command on the remote host via ssh.

    Uses `bash -lc` so the remote PATH picks up login-shell additions
    (/opt/cuda/bin, conda, etc.) — crucial for anything touching GPU
    build toolchains or language runtimes installed in user home.
    Also injects REMOTE_PATH_PREFIX so user-local install dirs are
    reachable.
    """
    # Prepend user-local install dirs, then run inside login shell.
    extended = f'export PATH="{REMOTE_PATH_PREFIX}:$PATH"; {remote_command}'
    wrapped = f"bash -lc {shlex.quote(extended)}"
    argv = ["ssh", "-o", "BatchMode=yes", host, wrapped]

    # On Windows + Git Bash / MSYS, ssh.exe's argv is preprocessed to
    # convert any `/foo/bar` arguments into `C:/Program Files/Git/foo/bar`,
    # which mangles every absolute remote path. Suppress this with
    # MSYS_NO_PATHCONV=1. No effect on real Linux/macOS.
    env = {**os.environ, "MSYS_NO_PATHCONV": "1", "MSYS2_ARG_CONV_EXCL": "*"}

    # When no input_text is provided, explicitly close child stdin. Without
    # this, ssh inherits the orchestrator's stdin and can hang waiting for
    # input in non-TTY contexts (e.g. when called from a subagent or
    # background task).
    run_kwargs: dict = dict(
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        encoding="utf-8",
        errors="replace",
    )
    if input_text is not None:
        run_kwargs["input"] = input_text
    else:
        run_kwargs["stdin"] = subprocess.DEVNULL

    # On Windows, ssh.exe launched from Python's subprocess can hang
    # indefinitely on capture_output if it inherits the parent's console
    # window. CREATE_NO_WINDOW prevents the inheritance and lets ssh.exe
    # exit cleanly when its work is done. No effect on Linux/macOS.
    if sys.platform == "win32":
        run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    return subprocess.run(argv, **run_kwargs)


def ssh_put_file(host: str, remote_path: str, content: str) -> None:
    """
    Write `content` to `remote_path` on the remote host.

    Uses stdin-redirect pattern (not scp) — scp is often denied by sandboxes
    and stdin-redirect avoids heredoc quoting entirely since the content
    never touches a shell.
    """
    # Use `cat > path` with the content piped in. No heredoc, no quoting of
    # content. mkdir -p the parent dir first in the same call.
    parent = os.path.dirname(remote_path)
    cmd = f"mkdir -p {qrp(parent)} && cat > {qrp(remote_path)}"
    result = ssh_run(host, cmd, input_text=content)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to write {remote_path} on {host}: "
            f"exit {result.returncode}, stderr: {result.stderr}"
        )


def ssh_check(host: str, remote_command: str, *, error_context: str = "") -> str:
    """Run a command, raise if it fails, return stdout."""
    result = ssh_run(host, remote_command)
    if result.returncode != 0:
        ctx = f" ({error_context})" if error_context else ""
        raise RuntimeError(
            f"Remote command failed{ctx} on {host}: "
            f"`{remote_command}`\nexit {result.returncode}\n"
            f"stderr: {result.stderr}"
        )
    return result.stdout


# --------------------------------------------------------------------------
# Remote worktree management
# --------------------------------------------------------------------------


def compute_worktree_path(repo_path: str, branch: str) -> str:
    """
    Worktrees live SIBLING to the repo, not inside it, under an
    `agent-remote-worktrees/` directory. Branch-name is used as the
    directory name, with slashes replaced.
    """
    parent = os.path.dirname(repo_path.rstrip("/"))
    safe_branch = branch.replace("/", "_")
    # Backwards compatibility check
    if branch.startswith("remote-claude"):
        return f"{parent}/remote-claude-worktrees/{safe_branch}"
    return f"{parent}/agent-remote-worktrees/{safe_branch}"


def ensure_worktree(host: str, repo_path: str, branch: str) -> tuple[str, str]:
    """
    Create or reuse a git worktree for `branch` on the remote.
    Returns (worktree_path, parent_commit_sha).
    """
    worktree_path = compute_worktree_path(repo_path, branch)

    # Check if the worktree already exists for this branch
    existing = ssh_check(
        host,
        f"git -C {qrp(repo_path)} worktree list --porcelain",
        error_context="list worktrees",
    )
    for block in existing.strip().split("\n\n"):
        if f"branch refs/heads/{branch}" in block:
            # Worktree already exists — reuse it.
            wt_line = [l for l in block.splitlines() if l.startswith("worktree ")][0]
            worktree_path = wt_line.split(" ", 1)[1]
            parent = ssh_check(
                host,
                f"git -C {qrp(worktree_path)} rev-parse HEAD",
            ).strip()
            return worktree_path, parent

    # Fresh worktree: create from current HEAD of the repo
    parent_commit = ssh_check(
        host,
        f"git -C {qrp(repo_path)} rev-parse HEAD",
        error_context="get parent commit",
    ).strip()

    ssh_check(
        host,
        f"git -C {qrp(repo_path)} worktree add -b {shlex.quote(branch)} "
        f"{qrp(worktree_path)} {shlex.quote(parent_commit)}",
        error_context="create worktree",
    )

    return worktree_path, parent_commit


def seed_settings(host: str, worktree_path: str, allowlist: list[str]) -> None:
    """
    Write a narrow .claude/settings.local.json into the worktree.
    This gives the spawned `claude -p` session exactly the permissions
    it needs, without requiring --permission-mode bypassPermissions.
    """
    settings = {
        "permissions": {
            "allow": allowlist,
        }
    }
    settings_path = f"{worktree_path}/.claude/settings.local.json"
    ssh_put_file(host, settings_path, json.dumps(settings, indent=2) + "\n")


# --------------------------------------------------------------------------
# The remote agent invocation
# --------------------------------------------------------------------------


def run_remote_agent(
    host: str,
    worktree_path: str,
    prompt: str,
    permission_mode: str,
    timeout: float,
    agent: str,
    model: str | None = None,
) -> tuple[int, str, str]:
    """
    Invoke the selected agent CLI on the remote in the worktree directory.
    Returns (exit_code, stdout, stderr).
    """
    prompt_file = f"{worktree_path}/.agent-prompt.txt"
    ssh_put_file(host, prompt_file, prompt)

    if agent == "claude":
        remote_cmd = (
            f"cd {qrp(worktree_path)} && "
            f"claude -p --permission-mode {shlex.quote(permission_mode)} "
            f"< {qrp(prompt_file)}"
        )
    elif agent == "agy":
        args_list = ["agy", "--print", "PROMPT_PLACEHOLDER"]
        if permission_mode == "plan":
            args_list.extend(["--mode", "plan"])
        elif permission_mode in ("acceptEdits", "bypassPermissions"):
            args_list.append("--dangerously-skip-permissions")
            args_list.extend(["--mode", "accept-edits"])
        if model:
            args_list.extend(["--model", model])

        args_json = json.dumps(args_list)
        py_cmd = (
            "import json, subprocess; "
            f"args = json.loads({args_json!r}); "
            f"args[args.index('PROMPT_PLACEHOLDER')] = open({prompt_file!r}).read(); "
            "subprocess.run(args)"
        )
        remote_cmd = f"cd {qrp(worktree_path)} && python3 -c {shlex.quote(py_cmd)}"
    elif agent == "opencode":
        opencode_args = ["opencode", "run"]
        if permission_mode in ("acceptEdits", "bypassPermissions"):
            opencode_args.append("--auto")
        if model:
            opencode_args.extend(["--model", model])

        args_json = json.dumps(opencode_args + ["PROMPT_PLACEHOLDER"])
        py_cmd = (
            "import json, subprocess; "
            f"args = json.loads({args_json!r}); "
            f"args[args.index('PROMPT_PLACEHOLDER')] = open({prompt_file!r}).read(); "
            "subprocess.run(args)"
        )
        remote_cmd = f"cd {qrp(worktree_path)} && python3 -c {shlex.quote(py_cmd)}"
    elif agent == "pi":
        pi_args = ["pi", "-p"]
        if model:
            pi_args.extend(["--model", model])

        args_json = json.dumps(pi_args + ["PROMPT_PLACEHOLDER"])
        py_cmd = (
            "import json, subprocess; "
            f"args = json.loads({args_json!r}); "
            f"args[args.index('PROMPT_PLACEHOLDER')] = open({prompt_file!r}).read(); "
            "subprocess.run(args)"
        )
        remote_cmd = f"cd {qrp(worktree_path)} && python3 -c {shlex.quote(py_cmd)}"
    elif agent == "codex":
        codex_args = ["codex", "exec"]
        if permission_mode in ("acceptEdits", "bypassPermissions"):
            codex_args.append("--dangerously-bypass-approvals-and-sandbox")
        if model:
            codex_args.extend(["--model", model])

        args_json = json.dumps(codex_args + ["PROMPT_PLACEHOLDER"])
        py_cmd = (
            "import json, subprocess; "
            f"args = json.loads({args_json!r}); "
            f"args[args.index('PROMPT_PLACEHOLDER')] = open({prompt_file!r}).read(); "
            "subprocess.run(args)"
        )
        remote_cmd = f"cd {qrp(worktree_path)} && python3 -c {shlex.quote(py_cmd)}"
    else:
        raise ValueError(f"Unknown agent: {agent}")

    result = ssh_run(host, remote_cmd, timeout=timeout)

    # Cleanup remains best-effort because the agent result is the primary outcome.
    try:
        ssh_run(host, f"rm -f {qrp(prompt_file)}")
    except (OSError, subprocess.SubprocessError) as exception:
        cleanup_warning = f"warning: could not remove remote prompt file: {exception}"
        stderr = "\n".join(part for part in (stderr, cleanup_warning) if part)

    return result.returncode, result.stdout, result.stderr


# --------------------------------------------------------------------------
# Result collection
# --------------------------------------------------------------------------


def collect_result(
    host: str,
    worktree_path: str,
    branch: str,
    parent_commit: str,
    agent_exit_code: int,
    agent_stdout: str,
    agent_stderr: str,
) -> RunResult:
    """
    After the agent exits, figure out what changed in the worktree and
    build a RunResult.
    """
    # New commit (if agent committed something)
    new_commit_raw = ssh_check(
        host,
        f"git -C {qrp(worktree_path)} rev-parse HEAD",
    ).strip()
    new_commit: str | None = new_commit_raw if new_commit_raw != parent_commit else None

    # Files changed: diff against parent commit (includes committed changes)
    # plus any uncommitted changes (staged + unstaged + untracked).
    diff_cmd = (
        f"git -C {qrp(worktree_path)} diff --name-only {shlex.quote(parent_commit)} && "
        f"git -C {qrp(worktree_path)} ls-files --others --exclude-standard"
    )
    diff_out = ssh_run(host, diff_cmd).stdout
    files_changed = sorted(
        set(line.strip() for line in diff_out.splitlines() if line.strip())
    )

    cleanup_command = (
        f"python agent-remote.py cleanup "
        f"--host {shlex.quote(host)} "
        f"--branch {shlex.quote(branch)}"
    )

    return RunResult(
        host=host,
        branch=branch,
        worktree_path=worktree_path,
        parent_commit=parent_commit,
        new_commit=new_commit,
        files_changed=files_changed,
        agent_exit_code=agent_exit_code,
        # Tail size: enough to capture verification output from a multi-step
        # remote agent (systemctl status, journalctl excerpts, benchmark
        # matrices, etc.).
        stdout_tail=agent_stdout[-20000:] if agent_stdout else "",
        stderr_tail=agent_stderr[-5000:] if agent_stderr else "",
        cleanup_command=cleanup_command,
    )


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    # Reverse Git Bash MSYS path mangling on user-supplied remote paths
    args.repo_path = unmangle_msys_path(args.repo_path)

    # Permission mode guardrail
    if args.permission_mode == "bypassPermissions":
        if (
            os.environ.get("REMOTE_AGENT_ALLOW_BYPASS") != "1"
            and os.environ.get("REMOTE_CLAUDE_ALLOW_BYPASS") != "1"
        ):
            print(
                "refused: --permission-mode bypassPermissions requires "
                "REMOTE_AGENT_ALLOW_BYPASS=1 in the environment.",
                file=sys.stderr,
            )
            return 2

    # Auto-generate branch name if not provided
    branch = args.branch or f"agent-remote/auto-{int(time.time())}"

    timeout_str = (
        os.environ.get("REMOTE_AGENT_TIMEOUT")
        or os.environ.get("REMOTE_CLAUDE_TIMEOUT")
        or "3600"
    )
    timeout = float(timeout_str)

    try:
        worktree_path, parent_commit = ensure_worktree(
            args.host,
            args.repo_path,
            branch,
        )

        # Resolve agent
        agent = args.agent
        if not agent:
            if os.environ.get("ANTIGRAVITY_AGENT") == "1":
                agent = "agy"
            elif any(k.startswith("OPENCODE_") for k in os.environ.keys()):
                agent = "opencode"
            elif (
                any(k.startswith("CLAUDE_CODE") for k in os.environ.keys())
                or os.environ.get("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB") == "1"
            ):
                agent = "claude"
            elif any(k.startswith("PI_") for k in os.environ.keys()):
                agent = "pi"
            elif any(k.startswith("CODEX_") for k in os.environ.keys()):
                agent = "codex"
            else:
                agent = "opencode"

        # Seed settings only for Claude
        if agent == "claude":
            allowlist = list(DEFAULT_REMOTE_ALLOWLIST)
            if args.extra_allow:
                allowlist.extend(args.extra_allow)
            seed_settings(args.host, worktree_path, allowlist)

        exit_code, stdout, stderr = run_remote_agent(
            host=args.host,
            worktree_path=worktree_path,
            prompt=args.prompt,
            permission_mode=args.permission_mode,
            timeout=timeout,
            agent=agent,
            model=args.model,
        )

        result = collect_result(
            args.host,
            worktree_path,
            branch,
            parent_commit,
            exit_code,
            stdout,
            stderr,
        )
        print(result.to_json())
        return 0 if result.success else 1

    except subprocess.TimeoutExpired:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "timeout",
                    "host": args.host,
                    "branch": branch,
                    "timeout_seconds": timeout,
                },
                indent=2,
            ),
            file=sys.stdout,
        )
        return 3
    except Exception as e:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "host": args.host,
                    "branch": branch,
                },
                indent=2,
            ),
            file=sys.stdout,
        )
        return 4


def cmd_cleanup(args: argparse.Namespace) -> int:
    """
    Remove a worktree and its branch from the remote.
    Does NOT delete any commits — if the caller merged the branch elsewhere,
    those commits survive.
    """
    if not args.repo_path:
        print(
            "cleanup: --repo-path is required so we can find the worktree",
            file=sys.stderr,
        )
        return 2
    args.repo_path = unmangle_msys_path(args.repo_path)
    try:
        worktree_path = compute_worktree_path(args.repo_path, args.branch)
        ssh_check(
            args.host,
            f"git -C {qrp(args.repo_path)} worktree remove --force {qrp(worktree_path)} && "
            f"git -C {qrp(args.repo_path)} branch -D {shlex.quote(args.branch)}",
            error_context="remove worktree and branch",
        )
        print(
            json.dumps(
                {
                    "success": True,
                    "host": args.host,
                    "branch": args.branch,
                    "removed": worktree_path,
                },
                indent=2,
            )
        )
        return 0
    except Exception as e:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                indent=2,
            ),
            file=sys.stdout,
        )
        return 1


def cmd_probe(args: argparse.Namespace) -> int:
    """
    Sanity-check the remote environment. Prints a JSON object with:
    user, hostname, uname, repo-path-exists, git-version, claude-version,
    agy-version, opencode-version, python-version, PATH.
    """
    args.repo_path = unmangle_msys_path(args.repo_path)
    try:
        probe_cmd = (
            "printf '{'; "
            'printf \'"user":"%s",\' "$(whoami)"; '
            'printf \'"hostname":"%s",\' "$(hostnamectl --static 2>/dev/null || cat /etc/hostname)"; '
            'printf \'"uname":"%s",\' "$(uname -srm)"; '
            f"printf '\"repo_path_exists\":%s,' "
            f'"$(test -d {qrp(args.repo_path)}/.git && echo true || echo false)"; '
            'printf \'"git":"%s",\' "$(git --version 2>/dev/null || echo missing)"; '
            'printf \'"claude":"%s",\' "$(claude --version 2>/dev/null || echo missing)"; '
            'printf \'"agy":"%s",\' "$(agy --version 2>/dev/null || echo missing)"; '
            'printf \'"opencode":"%s",\' "$(opencode --version 2>/dev/null || echo missing)"; '
            'printf \'"pi":"%s",\' "$(pi --version 2>/dev/null || echo missing)"; '
            'printf \'"codex":"%s",\' "$(codex --version 2>/dev/null || echo missing)"; '
            'printf \'"python":"%s",\' "$(python3 --version 2>/dev/null || echo missing)"; '
            'printf \'"path":"%s"\' "$PATH"; '
            "printf '}\\n'"
        )
        result = ssh_run(args.host, probe_cmd)
        if result.returncode != 0:
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": "probe command failed",
                        "stderr": result.stderr,
                    },
                    indent=2,
                )
            )
            return 1
        # Validate JSON, re-emit
        parsed = json.loads(result.stdout)
        parsed["success"] = True
        parsed["host"] = args.host
        print(json.dumps(parsed, indent=2))
        return 0
    except Exception as e:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                indent=2,
            )
        )
        return 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-remote",
        description="Spawn an agent session on a remote host in an isolated worktree.",
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    # run
    p_run = subparsers.add_parser(
        "run",
        help="Run a prompt on a remote host in a fresh worktree.",
    )
    p_run.add_argument("--host", required=True, help="user@hostname for ssh")
    p_run.add_argument(
        "--repo-path", required=True, help="path to the existing git repo on the remote"
    )
    p_run.add_argument(
        "--prompt", required=True, help="prompt to pass to the remote agent session"
    )
    p_run.add_argument(
        "--branch",
        default=None,
        help="branch name for the worktree (default: agent-remote/auto-<epoch>)",
    )
    p_run.add_argument(
        "--permission-mode",
        default="acceptEdits",
        choices=["default", "acceptEdits", "bypassPermissions", "plan"],
        help="permission mode for the spawned agent",
    )
    p_run.add_argument(
        "--extra-allow",
        action="append",
        default=[],
        help="additional permission rule(s) to add to the remote settings.local.json (only for claude)",
    )
    p_run.add_argument(
        "--agent",
        default=None,
        choices=["claude", "opencode", "agy", "pi", "codex"],
        help="agent runner to spawn on the remote (defaults to auto-detection: agy if ANTIGRAVITY_AGENT=1, else opencode)",
    )
    p_run.add_argument(
        "--model",
        "-m",
        default=None,
        help="model/provider to use for the agent session (e.g. ollama/qwen3.5-9b, only for agy/opencode/pi/codex)",
    )
    p_run.set_defaults(func=cmd_run)

    # cleanup
    p_cleanup = subparsers.add_parser(
        "cleanup",
        help="Remove a worktree and its branch on the remote.",
    )
    p_cleanup.add_argument("--host", required=True)
    p_cleanup.add_argument("--branch", required=True)
    p_cleanup.add_argument("--repo-path", required=True)
    p_cleanup.set_defaults(func=cmd_cleanup)

    # probe
    p_probe = subparsers.add_parser(
        "probe",
        help="Sanity-check a remote host's environment.",
    )
    p_probe.add_argument("--host", required=True)
    p_probe.add_argument("--repo-path", required=True)
    p_probe.set_defaults(func=cmd_probe)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
