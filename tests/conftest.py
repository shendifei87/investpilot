"""Shared pytest fixtures for InvestPilot tests."""


import pytest


@pytest.fixture
def tmp_workspace(tmp_path):
    """Provide a temporary workspace directory, isolated from real workspaces/.

    Returns a Path to the temp dir. Each test gets its own clean workspace.
    """
    ws = tmp_path / "test_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


@pytest.fixture
def tmp_workspaces_dir(tmp_path):
    """Provide a temporary workspaces/ root (mimics WORKSPACES_DIR).

    Modules that import WORKSPACES_DIR from config.settings can be
    patched to use this directory instead.
    """
    ws_root = tmp_path / "workspaces"
    ws_root.mkdir(parents=True, exist_ok=True)
    return ws_root
