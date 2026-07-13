"""Native package smoke tests (state + git)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("agent_lsp_state")
pytest.importorskip("agent_lsp_git")

from agent_lsp_git import GitService
from agent_lsp_state import StateStore


def test_state_session_container(tmp_path: Path) -> None:
    store = StateStore(str(tmp_path / "s.db"))
    sid = store.create_session(meta='{"t":1}')
    wid = store.create_workspace("p", str(tmp_path / "ws"), ref_name="main")
    store.set_active_workspace(sid, wid)
    store.bind_container(sid, "c1", "img", "go", host_port=3737, runtime_mode="container")
    store.set_index_status(sid, "ready")
    row = store.get_session(sid)
    assert row["index_status"] == "ready"
    assert len(store.list_containers(sid)) == 1
    store.close_session(sid)
    assert store.get_session(sid)["index_status"] == "closed"


def test_git_worktree_roundtrip(tmp_path: Path) -> None:
    git = GitService()
    bare = git.init_bare(str(tmp_path / "p.git"))
    wt = git.add_worktree(bare, str(tmp_path / "wt"), "main")
    (Path(wt) / "hello.txt").write_text("hi", encoding="utf-8")
    cid = git.commit(wt, "add hello", ["hello.txt"])
    assert len(cid) >= 7
    wt2 = git.add_worktree(bare, str(tmp_path / "wt2"), "main")
    assert (Path(wt2) / "hello.txt").read_text(encoding="utf-8") == "hi"
    bare2 = git.import_local(wt, str(tmp_path / "mirror.git"))
    assert Path(bare2).exists()
