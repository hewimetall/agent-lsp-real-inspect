"""Native extension smoke tests (state + git via unified _tasks)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("agent_lsp._tasks")

from agent_lsp._tasks import GitService, StateStore


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
    bare = git.init_bare(str(tmp_path / "repo.git"))
    wt = git.add_worktree(bare, str(tmp_path / "wt"), ref_name="HEAD")
    (Path(wt) / "README").write_text("hi\n", encoding="utf-8")
    sha = git.commit(wt, "init", paths=["README"])
    assert len(sha) >= 7
