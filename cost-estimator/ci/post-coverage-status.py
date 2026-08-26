"""Post the pr-crew coverage commit status from a pytest coverage report."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path


def percent_from_coverage_json(path: Path) -> float:
    """Read the total line-coverage percentage from pytest-cov JSON."""

    with path.open(encoding="utf-8") as handle:
        return float(json.load(handle)["totals"]["percent_covered"])


def ssl_context() -> ssl.SSLContext:
    """Build a verifying context that includes a runner-mounted root CA."""

    context = ssl.create_default_context()
    for variable in ("CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS", "GIT_SSL_CAINFO"):
        certificate = os.environ.get(variable)
        if certificate and Path(certificate).is_file():
            context.load_verify_locations(cafile=certificate)
            break
    return context


def post_status(state: str, description: str) -> None:
    """Post one commit status to the current Gitea repository."""

    server = os.environ["GITHUB_SERVER_URL"]
    repository = os.environ["GITHUB_REPOSITORY"]
    commit = os.environ["GITHUB_SHA"]
    run_identifier = os.environ.get("GITHUB_RUN_ID", "")
    body = json.dumps(
        {
            "context": "pr-crew/coverage",
            "state": state,
            "description": description,
            "target_url": f"{server}/{repository}/actions/runs/{run_identifier}",
        }
    ).encode()
    request = urllib.request.Request(
        f"{server}/api/v1/repos/{repository}/statuses/{commit}",
        data=body,
        method="POST",
        headers={
            "Authorization": f"token {os.environ['GITHUB_TOKEN']}",
            "Content-Type": "application/json",
        },
    )
    urllib.request.urlopen(request, context=ssl_context()).read()


def main(arguments: list[str]) -> int:
    """Read coverage and post success, or post an error if it is unreadable."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "coverage_json", nargs="?", type=Path, default=Path("coverage.json")
    )
    parsed_arguments = parser.parse_args(arguments[1:])
    try:
        percent = percent_from_coverage_json(parsed_arguments.coverage_json)
    except (KeyError, OSError, TypeError, ValueError) as error:
        print(f"coverage measurement failed: {error}", file=sys.stderr)
        post_status("error", "coverage measurement failed")
        return 0

    percent = round(percent, 2)
    description = f"{percent}% line coverage"
    post_status("success", description)
    print(f"posted pr-crew/coverage success: {description}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
