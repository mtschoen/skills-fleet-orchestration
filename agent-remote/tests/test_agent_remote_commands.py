"""Tests for remote agent invocation and CLI commands."""

from __future__ import annotations

import argparse
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from tests.agent_remote_test_support import (
    agent_remote,
    completed_process,
    run_arguments,
)


class RemoteAgentInvocationTests(unittest.TestCase):
    def invoke(
        self, agent: str, permission_mode: str = "acceptEdits", model: str | None = None
    ) -> str:
        with (
            patch.object(agent_remote, "ssh_put_file") as put_file,
            patch.object(
                agent_remote,
                "ssh_run",
                side_effect=[
                    completed_process(7, "stdout", "stderr"),
                    completed_process(),
                ],
            ) as ssh_run,
        ):
            result = agent_remote.run_remote_agent(
                "host", "/srv/worktree", "prompt", permission_mode, 30, agent, model
            )

        self.assertEqual(result, (7, "stdout", "stderr"))
        put_file.assert_called_once_with(
            "host", "/srv/worktree/.agent-prompt.txt", "prompt"
        )
        self.assertEqual(ssh_run.call_args_list[0].kwargs["timeout"], 30)
        self.assertIn("rm -f", ssh_run.call_args_list[1].args[1])
        return ssh_run.call_args_list[0].args[1]

    def test_builds_claude_command(self) -> None:
        with patch.object(agent_remote.sys, "platform", "linux"):
            command = self.invoke("claude", "plan")
        self.assertIn("claude -p --permission-mode plan", command)
        self.assertIn("< /srv/worktree/.agent-prompt.txt", command)

    def test_builds_agy_commands_for_plan_and_edit_modes(self) -> None:
        plan_command = self.invoke("agy", "plan", "provider/model")
        edit_command = self.invoke("agy", "acceptEdits")
        self.assertIn('"--mode", "plan"', plan_command)
        self.assertIn('"--model", "provider/model"', plan_command)
        self.assertIn('"--dangerously-skip-permissions"', edit_command)
        self.assertIn('"accept-edits"', edit_command)

    def test_builds_opencode_pi_and_codex_commands(self) -> None:
        opencode_command = self.invoke("opencode", model="provider/model")
        pi_command = self.invoke("pi", model="provider/model")
        codex_command = self.invoke("codex")
        self.assertIn('"opencode", "run", "--auto"', opencode_command)
        self.assertIn('"pi", "-p"', pi_command)
        self.assertIn('"codex", "exec", "--dangerously-bypass', codex_command)

    def test_rejects_unknown_agent(self) -> None:
        with patch.object(agent_remote, "ssh_put_file"):
            with self.assertRaisesRegex(ValueError, "Unknown agent"):
                agent_remote.run_remote_agent(
                    "host", "/worktree", "prompt", "default", 1, "unknown"
                )

    def test_cleanup_failure_appends_warning_without_raising(self) -> None:
        with (
            patch.object(agent_remote, "ssh_put_file"),
            patch.object(
                agent_remote,
                "ssh_run",
                side_effect=[
                    completed_process(0, "stdout", "stderr"),
                    subprocess.TimeoutExpired("ssh", 5),
                ],
            ),
        ):
            exit_code, stdout, stderr = agent_remote.run_remote_agent(
                "host", "/srv/worktree", "prompt", "acceptEdits", 30, "claude"
            )

        self.assertEqual((exit_code, stdout), (0, "stdout"))
        self.assertIn("stderr", stderr)
        self.assertIn("warning: could not remove remote prompt file", stderr)


class RunCommandTests(unittest.TestCase):
    def test_refuses_unapproved_bypass_mode(self) -> None:
        arguments = run_arguments(permission_mode="bypassPermissions")
        error = StringIO()
        with (
            patch.dict(agent_remote.os.environ, {}, clear=True),
            redirect_stderr(error),
        ):
            exit_code = agent_remote.cmd_run(arguments)

        self.assertEqual(exit_code, 2)
        self.assertIn("REMOTE_AGENT_ALLOW_BYPASS=1", error.getvalue())

    def test_runs_claude_and_seeds_extended_allowlist(self) -> None:
        arguments = run_arguments(agent="claude", extra_allow=["Bash(sudo *)"])
        result = agent_remote.RunResult(
            "host", "branch", "/worktree", "parent", "child", [], 0, "", "", "cleanup"
        )
        output = StringIO()
        with (
            patch.object(
                agent_remote, "unmangle_msys_path", return_value="/repo"
            ) as unmangle,
            patch.object(
                agent_remote, "ensure_worktree", return_value=("/worktree", "parent")
            ),
            patch.object(agent_remote, "seed_settings") as seed_settings,
            patch.object(
                agent_remote, "run_remote_agent", return_value=(0, "out", "err")
            ),
            patch.object(agent_remote, "collect_result", return_value=result),
            patch.dict(
                agent_remote.os.environ, {"REMOTE_AGENT_TIMEOUT": "12"}, clear=True
            ),
            redirect_stdout(output),
        ):
            exit_code = agent_remote.cmd_run(arguments)

        self.assertEqual(exit_code, 0)
        unmangle.assert_called_once_with("/srv/project")
        self.assertEqual(arguments.repo_path, "/repo")
        self.assertEqual(
            seed_settings.call_args.args[2],
            agent_remote.DEFAULT_REMOTE_ALLOWLIST + ["Bash(sudo *)"],
        )
        self.assertTrue(json.loads(output.getvalue())["success"])

    def test_returns_one_when_agent_result_is_unsuccessful(self) -> None:
        arguments = run_arguments()
        result = agent_remote.RunResult(
            "host", "branch", "/worktree", "parent", None, [], 5, "", "", "cleanup"
        )
        with (
            patch.object(
                agent_remote, "ensure_worktree", return_value=("/worktree", "parent")
            ),
            patch.object(agent_remote, "run_remote_agent", return_value=(5, "", "")),
            patch.object(agent_remote, "collect_result", return_value=result),
            patch.dict(agent_remote.os.environ, {}, clear=True),
            redirect_stdout(StringIO()),
        ):
            self.assertEqual(agent_remote.cmd_run(arguments), 1)

    def test_autodetects_each_supported_agent_environment(self) -> None:
        scenarios = [
            ({"ANTIGRAVITY_AGENT": "1"}, "agy"),
            ({"OPENCODE_TEST": "1"}, "opencode"),
            ({"CLAUDE_CODE_TEST": "1"}, "claude"),
            ({"CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1"}, "claude"),
            ({"PI_TEST": "1"}, "pi"),
            ({"CODEX_TEST": "1"}, "codex"),
            ({}, "opencode"),
        ]
        for environment, expected_agent in scenarios:
            with self.subTest(expected_agent=expected_agent, environment=environment):
                arguments = run_arguments(agent=None)
                result = agent_remote.RunResult(
                    "host",
                    "branch",
                    "/worktree",
                    "parent",
                    None,
                    [],
                    0,
                    "",
                    "",
                    "cleanup",
                )
                with (
                    patch.object(
                        agent_remote,
                        "ensure_worktree",
                        return_value=("/worktree", "parent"),
                    ),
                    patch.object(agent_remote, "seed_settings"),
                    patch.object(
                        agent_remote, "run_remote_agent", return_value=(0, "", "")
                    ) as run_agent,
                    patch.object(agent_remote, "collect_result", return_value=result),
                    patch.dict(agent_remote.os.environ, environment, clear=True),
                    redirect_stdout(StringIO()),
                ):
                    exit_code = agent_remote.cmd_run(arguments)

                self.assertEqual(exit_code, 0)
                self.assertEqual(run_agent.call_args.kwargs["agent"], expected_agent)

    def test_generates_branch_and_uses_configured_timeout(self) -> None:
        arguments = run_arguments(branch=None)
        result = agent_remote.RunResult(
            "host", "branch", "/worktree", "parent", None, [], 0, "", "", "cleanup"
        )
        with (
            patch.object(agent_remote.time, "time", return_value=1234),
            patch.object(
                agent_remote, "ensure_worktree", return_value=("/worktree", "parent")
            ) as ensure,
            patch.object(
                agent_remote, "run_remote_agent", return_value=(0, "", "")
            ) as run_agent,
            patch.object(agent_remote, "collect_result", return_value=result),
            patch.dict(
                agent_remote.os.environ, {"REMOTE_AGENT_TIMEOUT": "42"}, clear=True
            ),
            redirect_stdout(StringIO()),
        ):
            agent_remote.cmd_run(arguments)

        self.assertEqual(ensure.call_args.args[2], "agent-remote/auto-1234")
        self.assertEqual(run_agent.call_args.kwargs["timeout"], 42)

    def test_reports_timeout_and_other_exceptions_as_json(self) -> None:
        scenarios = [
            (subprocess.TimeoutExpired("ssh", 5), 3, "timeout"),
            (RuntimeError("broken"), 4, "RuntimeError"),
        ]
        for exception, expected_code, expected_error in scenarios:
            with self.subTest(expected_code=expected_code):
                output = StringIO()
                with (
                    patch.object(
                        agent_remote, "ensure_worktree", side_effect=exception
                    ),
                    patch.dict(agent_remote.os.environ, {}, clear=True),
                    redirect_stdout(output),
                ):
                    exit_code = agent_remote.cmd_run(run_arguments())
                payload = json.loads(output.getvalue())
                self.assertEqual(exit_code, expected_code)
                self.assertIn(
                    expected_error, payload.get("error_type", payload["error"])
                )


class CleanupCommandTests(unittest.TestCase):
    def test_requires_repo_path(self) -> None:
        arguments = argparse.Namespace(host="host", branch="branch", repo_path="")
        with redirect_stderr(StringIO()) as error:
            exit_code = agent_remote.cmd_cleanup(arguments)
        self.assertEqual(exit_code, 2)
        self.assertIn("--repo-path is required", error.getvalue())

    def test_removes_worktree_and_branch(self) -> None:
        arguments = argparse.Namespace(
            host="host", branch="agent-remote/task", repo_path="/srv/project"
        )
        output = StringIO()
        with (
            patch.object(agent_remote, "ssh_check") as ssh_check,
            redirect_stdout(output),
        ):
            exit_code = agent_remote.cmd_cleanup(arguments)

        self.assertEqual(exit_code, 0)
        self.assertIn("worktree remove --force", ssh_check.call_args.args[1])
        self.assertEqual(json.loads(output.getvalue())["branch"], "agent-remote/task")

    def test_reports_cleanup_failure(self) -> None:
        arguments = argparse.Namespace(host="host", branch="branch", repo_path="/repo")
        output = StringIO()
        with (
            patch.object(
                agent_remote, "ssh_check", side_effect=RuntimeError("failure")
            ),
            redirect_stdout(output),
        ):
            exit_code = agent_remote.cmd_cleanup(arguments)
        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(output.getvalue())["error_type"], "RuntimeError")


class ProbeCommandTests(unittest.TestCase):
    def probe_arguments(self) -> argparse.Namespace:
        return argparse.Namespace(host="host", repo_path="/srv/project")

    def test_emits_validated_probe_result(self) -> None:
        output = StringIO()
        with (
            patch.object(
                agent_remote,
                "ssh_run",
                return_value=completed_process(stdout='{"user":"worker"}\n'),
            ) as ssh_run,
            redirect_stdout(output),
        ):
            exit_code = agent_remote.cmd_probe(self.probe_arguments())

        self.assertEqual(exit_code, 0)
        self.assertIn("repo_path_exists", ssh_run.call_args.args[1])
        self.assertEqual(
            json.loads(output.getvalue()),
            {"user": "worker", "success": True, "host": "host"},
        )

    def test_reports_remote_probe_failure(self) -> None:
        output = StringIO()
        with (
            patch.object(
                agent_remote,
                "ssh_run",
                return_value=completed_process(1, stderr="offline"),
            ),
            redirect_stdout(output),
        ):
            exit_code = agent_remote.cmd_probe(self.probe_arguments())
        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(output.getvalue())["stderr"], "offline")

    def test_reports_invalid_probe_json(self) -> None:
        output = StringIO()
        with (
            patch.object(
                agent_remote,
                "ssh_run",
                return_value=completed_process(stdout="not json"),
            ),
            redirect_stdout(output),
        ):
            exit_code = agent_remote.cmd_probe(self.probe_arguments())
        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(output.getvalue())["error_type"], "JSONDecodeError")


class ParserTests(unittest.TestCase):
    def test_parser_accepts_all_subcommands(self) -> None:
        parser = agent_remote.build_parser()
        run = parser.parse_args(
            [
                "run",
                "--host",
                "host",
                "--repo-path",
                "/repo",
                "--prompt",
                "prompt",
                "--agent",
                "codex",
                "--model",
                "model",
                "--extra-allow",
                "Read(/tmp/*)",
            ]
        )
        cleanup = parser.parse_args(
            ["cleanup", "--host", "host", "--branch", "branch", "--repo-path", "/repo"]
        )
        probe = parser.parse_args(["probe", "--host", "host", "--repo-path", "/repo"])

        self.assertIs(run.func, agent_remote.cmd_run)
        self.assertEqual(run.agent, "codex")
        self.assertEqual(run.extra_allow, ["Read(/tmp/*)"])
        self.assertIs(cleanup.func, agent_remote.cmd_cleanup)
        self.assertIs(probe.func, agent_remote.cmd_probe)

    def test_main_dispatches_to_selected_command(self) -> None:
        with patch.object(agent_remote, "build_parser") as build_parser:
            build_parser.return_value.parse_args.return_value = argparse.Namespace(
                func=lambda arguments: 23
            )
            self.assertEqual(agent_remote.main(["probe"]), 23)


if __name__ == "__main__":
    unittest.main()
