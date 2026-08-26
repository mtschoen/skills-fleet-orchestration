"""Shared fixtures for exercising the script entry points."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


REPOSITORY_ROOT = Path(__file__).parent.parent
SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIRECTORY))


@pytest.fixture
def load_script():
    """Load a script whose filename is not a valid Python module name."""

    loaded_names: list[str] = []

    def load(filename: str):
        module_name = f"test_loaded_{filename.removesuffix('.py').replace('-', '_')}"
        specification = importlib.util.spec_from_file_location(
            module_name,
            SCRIPTS_DIRECTORY / filename,
        )
        assert specification is not None
        assert specification.loader is not None
        module = importlib.util.module_from_spec(specification)
        sys.modules[module_name] = module
        loaded_names.append(module_name)
        specification.loader.exec_module(module)
        return module

    yield load

    for module_name in loaded_names:
        sys.modules.pop(module_name, None)


@pytest.fixture
def workspace_directory() -> Iterator[Path]:
    """Provide a disposable directory without writing outside the worktree."""

    with TemporaryDirectory(
        prefix="cost-estimator-test-", dir=Path(__file__).parent
    ) as path:
        yield Path(path)
