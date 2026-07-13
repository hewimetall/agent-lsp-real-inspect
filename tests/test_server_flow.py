"""MCP tool smoke via direct function calls (no stdio)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("agent_lsp_state")
pytest.importorskip("agent_lsp_git")

from agent_lsp import paths as paths_mod
from agent_lsp import server


def test_onboard_empty_project(tmp_path: Path) -> None:
    paths_mod.STATE_DIR = tmp_path / "state"
    paths_mod.PROJECTS_DIR = tmp_path / "projects"
    paths_mod.WORKSPACES_DIR = tmp_path / "workspaces"
    paths_mod.CACHE_DIR = tmp_path / "cache"
    server._state = None
    server._git = None

    created = server.create_session()
    sid = created["session_id"]
    proj = server.create_project("demo")
    assert "bare" in proj
    co = server.checkout_workspace(sid, "demo")
    assert co.get("workspace_id")
    assert Path(co["path"]).exists()
    sess = server.get_session(sid)
    assert sess["active_workspace_id"] == co["workspace_id"]
    closed = server.close_session(sid)
    assert closed["closed"] is True
