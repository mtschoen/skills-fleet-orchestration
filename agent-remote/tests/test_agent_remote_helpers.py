"""Tests for path, SSH, worktree, and result helpers."""

from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from tests.agent_remote_test_support import agent_remote, completed_process


class RunResultTests(unittest.TestCase):
    def test_serializes_success_and_legacy_exit_code(self) -> None:
        result = agent_remote.RunResult(
            host="worker@example",
            branch="agent-remote/task",
            worktree_path="/srv/worktree",
            parent_commit="parent",
            new_commit="child",
            files_changed=["result.txt"],
            agent_exit_code=0,
            stdout_tail="output",
            stderr_tail="",
            cleanup_command="cleanup",
        )

        payload = json.loads(result.to_json())

        self.assertTrue(result.success)
        self.assertEqual(payload["agent_exit_code"], 0)
        self.assertEqual(payload["claude_exit_code"], 0)
        self.assertEqual(payload["new_commit"], "child")

    def test_nonzero_exit_is_unsuccessful(self) -> None:
        result = agent_remote.RunResult(
            "host", "branch", "/worktree", "parent", None, [], 7, "", "", "cleanup"
        )

        self.assertFalse(result.success)


class PathTests(unittest.TestCase):
    def test_remote_path_mangling_only_applies_on_windows(self) -> None:
        with patch.object(agent_remote.sys, "platform", "win32"):
            self.assertEqual(agent_remote.rpath("/srv/project"), "//srv/project")
            self.assertEqual(agent_remote.rpath("//srv/project"), "//srv/project")
            self.assertEqual(agent_remote.rpath("relative/path"), "relative/path")
        with patch.object(agent_remote.sys, "platform", "linux"):
            self.assertEqual(agent_remote.rpath("/srv/project"), "/srv/project")

    def test_quoted_remote_path_uses_mangled_path(self) -> None:
        with patch.object(agent_remote, "rpath", return_value="path with spaces"):
            self.assertEqual(agent_remote.qrp("ignored"), "'path with spaces'")

    def test_unmangles_known_git_for_windows_prefixes(self) -> None:
        with patch.object(agent_remote.sys, "platform", "win32"):
            self.assertEqual(
                agent_remote.unmangle_msys_path(
                    "C:/Program Files/Git/home/user/project"
                ),
                "/home/user/project",
            )
            self.assertEqual(
                agent_remote.unmangle_msys_path(
                    "C:\\Program Files (x86)\\Git\\home\\user\\project"
                ),
                "/home/user/project",
            )
            self.assertEqual(
                agent_remote.unmangle_msys_path("D:/project"), "D:/project"
            )
        with patch.object(agent_remote.sys, "platform", "linux"):
            self.assertEqual(
                agent_remote.unmangle_msys_path("C:/Program Files/Git/home/user"),
                "C:/Program Files/Git/home/user",
            )

    def test_computes_current_and_legacy_worktree_paths(self) -> None:
        self.assertEqual(
            agent_remote.compute_worktree_path(
                "/srv/project/", "agent-remote/topic/branch"
            ),
            "/srv/agent-remote-worktrees/agent-remote_topic_branch",
        )
        self.assertEqual(
            agent_remote.compute_worktree_path("/srv/project", "remote-claude/topic"),
            "/srv/remote-claude-worktrees/remote-claude_topic",
        )


class SshTests(unittest.TestCase):
    def test_ssh_run_closes_stdin_and_builds_login_shell_command(self) -> None:
        with (
            patch.object(agent_remote.sys, "platform", "linux"),
            patch.object(
                agent_remote.subprocess, "run", return_value=completed_process()
            ) as run,
        ):
            result = agent_remote.ssh_run("worker@example", "whoami", timeout=12)

        self.assertEqual(result.returncode, 0)
        positional_arguments, keyword_arguments = run.call_args
        self.assertEqual(
            positional_arguments[0][:4],
            ["ssh", "-o", "BatchMode=yes", "worker@example"],
        )
        self.assertIn("bash -lc", positional_arguments[0][4])
        self.assertIn(agent_remote.REMOTE_PATH_PREFIX, positional_arguments[0][4])
        self.assertEqual(keyword_arguments["stdin"], subprocess.DEVNULL)
        self.assertEqual(keyword_arguments["timeout"], 12)
        self.assertEqual(keyword_arguments["encoding"], "utf-8")
        self.assertEqual(keyword_arguments["env"]["MSYS_NO_PATHCONV"], "1")

    def test_ssh_run_passes_input_and_windows_creation_flag(self) -> None:
        with (
            patch.object(agent_remote.sys, "platform", "win32"),
            patch.object(
                agent_remote.subprocess, "CREATE_NO_WINDOW", 134_217_728, create=True
            ),
            patch.object(
                agent_remote.subprocess, "run", return_value=completed_process()
            ) as run,
        ):
            agent_remote.ssh_run("host", "cat", input_text="content")

        keyword_arguments = run.call_args.kwargs
        self.assertEqual(keyword_arguments["input"], "content")
        self.assertNotIn("stdin", keyword_arguments)
        self.assertEqual(keyword_arguments["creationflags"], 134_217_728)

    def test_put_file_creates_parent_and_streams_content(self) -> None:
        with patch.object(
            agent_remote, "ssh_run", return_value=completed_process()
        ) as ssh_run:
            agent_remote.ssh_put_file("host", "/srv/worktree/file.txt", "contents")

        remote_command = ssh_run.call_args.args[1]
        self.assertIn("mkdir -p /srv/worktree", remote_command)
        self.assertIn("cat > /srv/worktree/file.txt", remote_command)
        self.assertEqual(ssh_run.call_args.kwargs["input_text"], "contents")

    def test_put_file_reports_remote_failure(self) -> None:
        with patch.object(
            agent_remote,
            "ssh_run",
            return_value=completed_process(5, stderr="permission denied"),
        ):
            with self.assertRaisesRegex(RuntimeError, "permission denied"):
                agent_remote.ssh_put_file("host", "/srv/file", "contents")

    def test_ssh_check_returns_stdout_or_raises_with_context(self) -> None:
        with patch.object(
            agent_remote, "ssh_run", return_value=completed_process(stdout="ok\n")
        ):
            self.assertEqual(agent_remote.ssh_check("host", "command"), "ok\n")
        with patch.object(
            agent_remote,
            "ssh_run",
            return_value=completed_process(9, stderr="failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, r"\(collect state\)"):
                agent_remote.ssh_check("host", "command", error_context="collect state")


class WorktreeTests(unittest.TestCase):
    def test_reuses_existing_worktree_and_reads_parent(self) -> None:
        listing = (
            "worktree /srv/other\nHEAD abc\nbranch refs/heads/other\n\n"
            "worktree /srv/existing\nHEAD def\nbranch refs/heads/agent-remote/task\n"
        )
        with patch.object(
            agent_remote, "ssh_check", side_effect=[listing, "parent-sha\n"]
        ) as ssh_check:
            result = agent_remote.ensure_worktree(
                "host", "/srv/project", "agent-remote/task"
            )

        self.assertEqual(result, ("/srv/existing", "parent-sha"))
        self.assertEqual(ssh_check.call_count, 2)

    def test_creates_missing_worktree_from_repository_head(self) -> None:
        with patch.object(
            agent_remote,
            "ssh_check",
            side_effect=[
                "worktree /srv/project\nHEAD abc\nbranch refs/heads/main\n",
                "abc\n",
                "",
            ],
        ) as ssh_check:
            result = agent_remote.ensure_worktree(
                "host", "/srv/project", "agent-remote/task"
            )

        self.assertEqual(
            result,
            ("/srv/agent-remote-worktrees/agent-remote_task", "abc"),
        )
        self.assertIn(
            "worktree add -b agent-remote/task", ssh_check.call_args_list[2].args[1]
        )

    def test_seed_settings_writes_expected_json(self) -> None:
        with patch.object(agent_remote, "ssh_put_file") as put_file:
            agent_remote.seed_settings("host", "/srv/worktree", ["Read", "Write"])

        self.assertEqual(
            put_file.call_args.args[:2],
            ("host", "/srv/worktree/.claude/settings.local.json"),
        )
        self.assertEqual(
            json.loads(put_file.call_args.args[2]),
            {"permissions": {"allow": ["Read", "Write"]}},
        )


class ResultCollectionTests(unittest.TestCase):
    def test_collects_commits_and_deduplicates_changed_files(self) -> None:
        with (
            patch.object(agent_remote, "ssh_check", return_value="child\n"),
            patch.object(
                agent_remote,
                "ssh_run",
                return_value=completed_process(stdout="z.txt\na.txt\nz.txt\n"),
            ),
        ):
            result = agent_remote.collect_result(
                "host",
                "/srv/worktree",
                "agent-remote/task",
                "parent",
                0,
                "x" * 20_001,
                "y" * 5_001,
            )

        self.assertEqual(result.new_commit, "child")
        self.assertEqual(result.files_changed, ["a.txt", "z.txt"])
        self.assertEqual(len(result.stdout_tail), 20_000)
        self.assertEqual(len(result.stderr_tail), 5_000)
        self.assertIn("--branch agent-remote/task", result.cleanup_command)

    def test_reports_no_new_commit_or_output(self) -> None:
        with (
            patch.object(agent_remote, "ssh_check", return_value="parent\n"),
            patch.object(agent_remote, "ssh_run", return_value=completed_process()),
        ):
            result = agent_remote.collect_result(
                "host", "/worktree", "branch", "parent", 1, "", ""
            )

        self.assertIsNone(result.new_commit)
        self.assertEqual(result.stdout_tail, "")
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
