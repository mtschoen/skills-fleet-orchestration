"""Contract tests for the pr-crew coverage status workflow."""

from __future__ import annotations

import importlib.util
import json
import runpy
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPOSITORY_ROOT / "ci" / "post-coverage-status.py"
WORKFLOW_PATH = REPOSITORY_ROOT / ".gitea" / "workflows" / "lint.yml"
CI_ENVIRONMENT = {
    "GITHUB_SERVER_URL": "https://gitea.example",
    "GITHUB_REPOSITORY": "owner/repo",
    "GITHUB_SHA": "deadbeef",
    "GITHUB_RUN_ID": "42",
    "GITHUB_TOKEN": "secret-token",
}


def load_status_module():
    """Load the status helper whose filename is not a Python identifier."""

    assert SCRIPT_PATH.is_file(), "coverage status helper has not been added"
    specification = importlib.util.spec_from_file_location(
        "post_coverage_status",
        SCRIPT_PATH,
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_workflow_runs_pytest_with_coverage_and_always_posts_status():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "pytest-cov" in workflow
    assert "pytest tests/ --cov=scripts --cov=ci" in workflow
    assert "--cov-report=json:coverage.json" in workflow
    assert "if: always()" in workflow
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow
    assert "python ci/post-coverage-status.py" in workflow


def test_percent_from_coverage_json(workspace_directory: Path):
    status_module = load_status_module()
    report = workspace_directory / "coverage.json"
    report.write_text('{"totals": {"percent_covered": 87.5}}', encoding="utf-8")

    assert status_module.percent_from_coverage_json(report) == 87.5


def test_ssl_context_adds_mounted_certificate_authority(workspace_directory: Path):
    status_module = load_status_module()
    certificate = workspace_directory / "runner-root.pem"
    certificate.write_text("certificate", encoding="utf-8")
    context = MagicMock()

    with (
        patch.dict("os.environ", {"CURL_CA_BUNDLE": str(certificate)}, clear=True),
        patch.object(status_module.ssl, "create_default_context", return_value=context),
    ):
        assert status_module.ssl_context() is context

    context.load_verify_locations.assert_called_once_with(cafile=str(certificate))


def test_ssl_context_uses_system_roots_without_mounted_certificate(
    workspace_directory: Path,
):
    status_module = load_status_module()
    context = MagicMock()

    with (
        patch.dict(
            "os.environ",
            {"GIT_SSL_CAINFO": str(workspace_directory / "missing.pem")},
            clear=True,
        ),
        patch.object(status_module.ssl, "create_default_context", return_value=context),
    ):
        assert status_module.ssl_context() is context

    context.load_verify_locations.assert_not_called()


def test_post_status_builds_gitea_request():
    status_module = load_status_module()
    captured: dict[str, object] = {}

    def fake_urlopen(request, context=None):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        captured["data"] = request.data
        return MagicMock(read=lambda: b"")

    with (
        patch.dict("os.environ", CI_ENVIRONMENT, clear=True),
        patch.object(status_module.urllib.request, "urlopen", side_effect=fake_urlopen),
    ):
        status_module.post_status("success", "98% line coverage")

    assert captured["url"] == (
        "https://gitea.example/api/v1/repos/owner/repo/statuses/deadbeef"
    )
    assert captured["headers"]["Authorization"] == "token secret-token"
    assert json.loads(captured["data"]) == {
        "context": "pr-crew/coverage",
        "state": "success",
        "description": "98% line coverage",
        "target_url": "https://gitea.example/owner/repo/actions/runs/42",
    }


def test_main_posts_measured_coverage(workspace_directory: Path):
    status_module = load_status_module()
    coverage_json = workspace_directory / "coverage.json"
    coverage_json.write_text(
        '{"totals": {"percent_covered": 91.234}}',
        encoding="utf-8",
    )

    with patch.object(status_module, "post_status") as post_status:
        result = status_module.main(["post-coverage-status", str(coverage_json)])

    assert result == 0
    post_status.assert_called_once_with("success", "91.23% line coverage")


def test_main_reports_measurement_errors(
    workspace_directory: Path,
    capsys,
):
    status_module = load_status_module()

    with patch.object(status_module, "post_status") as post_status:
        assert status_module.main(["post-coverage-status", "missing.json"]) == 0
        post_status.assert_called_once_with("error", "coverage measurement failed")
    assert "coverage measurement failed" in capsys.readouterr().err


def test_module_entrypoint(workspace_directory: Path):
    coverage_json = workspace_directory / "coverage.json"
    coverage_json.write_text(
        '{"totals": {"percent_covered": 100.0}}',
        encoding="utf-8",
    )

    with (
        patch("sys.argv", ["post-coverage-status", str(coverage_json)]),
        patch.dict("os.environ", CI_ENVIRONMENT, clear=True),
        patch("urllib.request.urlopen", return_value=MagicMock(read=lambda: b"")),
        pytest.raises(SystemExit) as exit_information,
    ):
        runpy.run_path(str(SCRIPT_PATH), run_name="__main__")

    assert exit_information.value.code == 0
