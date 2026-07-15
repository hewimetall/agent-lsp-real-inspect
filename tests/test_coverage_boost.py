"""Broad coverage tests for runtime_hub, worker, server helpers, lsp client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("agent_lsp._tasks")
pytest.importorskip("agent_lsp_state")
pytest.importorskip("agent_lsp_git")

from agent_lsp import paths as paths_mod
from agent_lsp import server
from agent_lsp.blast import blast_radius
from agent_lsp.lsp_client import LspClient, SymbolInfo
from agent_lsp.runtime_hub import RuntimeHub, SessionRuntime, _find_seed_file
from agent_lsp.worker import ScoutWorker


@pytest.fixture()
def data_dirs(tmp_path: Path) -> Path:
    paths_mod.STATE_DIR = tmp_path / "state"
    paths_mod.PROJECTS_DIR = tmp_path / "projects"
    paths_mod.WORKSPACES_DIR = tmp_path / "workspaces"
    paths_mod.CACHE_DIR = tmp_path / "cache"
    for d in (
        paths_mod.STATE_DIR,
        paths_mod.PROJECTS_DIR,
        paths_mod.WORKSPACES_DIR,
        paths_mod.CACHE_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
    server._state = None
    server._git = None
    server._tasks = None
    server._docker = None
    server._docker_error = "no-docker"
    return tmp_path


def test_find_seed_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x=1\n", encoding="utf-8")
    assert _find_seed_file(tmp_path, "python") is not None
    assert _find_seed_file(tmp_path / "empty", "go") is None


def test_runtime_hub_put_get_drop_warm(tmp_path: Path) -> None:
    hub = RuntimeHub()
    client = MagicMock()
    client.is_workspace_loaded.return_value = False
    client.wait_until_ready.return_value = True
    client.document_symbols.return_value = [
        SymbolInfo(name="F", kind=12, line=1, character=1, file=str(tmp_path / "a.py"))
    ]
    client.references.return_value = []
    (tmp_path / "a.py").write_text("def F():\n    pass\n", encoding="utf-8")
    rt = SessionRuntime(
        session_id="s1",
        workspace_path=tmp_path,
        language="python",
        runtime_mode="local",
        container_id="local-1",
        host_port=None,
        client=client,
        index_status="cold",
    )
    hub.put(rt)
    assert hub.get("s1") is rt
    warmed = hub.warm("s1", timeout=0.1)
    assert warmed.index_status == "ready"
    hub.shutdown("s1", docker=None)
    assert hub.get("s1") is None


def test_runtime_hub_ensure_local_stdio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_LSP_ALLOW_LOCAL", "1")
    hub = RuntimeHub()

    class DummyClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            self._workspace_loaded = False

        @classmethod
        def spawn_local(
            cls,
            root: Path,
            language_id: str,
            cmd: list[str],
            *,
            settings: dict[str, Any] | None = None,
            initialization_options: dict[str, Any] | None = None,
        ) -> DummyClient:
            return cls()

        def wait_until_ready(self, timeout: float = 120.0) -> bool:
            return True

        def document_symbols(self, file_path: str | Path) -> list[Any]:
            return []

        def references(self, *a: Any, **k: Any) -> list[Any]:
            return []

        def shutdown(self) -> None:
            return None

        def is_workspace_loaded(self) -> bool:
            return True

    monkeypatch.setattr("agent_lsp.runtime_hub.LspClient", DummyClient)
    monkeypatch.setattr(
        "agent_lsp.runtime_hub.get_runtime",
        lambda language: type(
            "R",
            (),
            {
                "language": language,
                "image": "x",
                "cmd": ["true"],
                "local_cmd": ["true"],  # no {port} → stdio path
                "container_workdir": "/workspace",
            },
        )(),
    )
    rt = hub.ensure_local("sx", tmp_path, "python")
    assert rt.runtime_mode == "local"
    assert rt.client is not None


def test_worker_warm_and_errors(data_dirs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "wake_worker", lambda tasks: ScoutWorker(tasks))
    from agent_lsp import worker as worker_mod
    import agent_lsp.runtime_hub as rh

    if worker_mod._worker:
        worker_mod._worker.stop()
        worker_mod._worker = None

    sid = server.create_session()["session_id"]
    server.create_project("p1")
    co = server.checkout_workspace(sid, "p1")
    tid = server.get_tasks().submit(sid, co["path"], "nope")
    w = ScoutWorker(server.get_tasks())
    assert w.process_one() is True
    assert server.get_tasks().get(tid)["status"] == "error"

    hub = RuntimeHub()
    client = MagicMock()
    client.wait_until_ready.return_value = True
    client.document_symbols.return_value = []
    client._workspace_loaded = False
    hub.put(
        SessionRuntime(
            session_id=sid,
            workspace_path=Path(co["path"]),
            language="python",
            runtime_mode="local",
            container_id="c",
            client=client,
        )
    )
    monkeypatch.setattr(rh, "HUB", hub)
    monkeypatch.setattr(server, "HUB", hub)

    q = server.enqueue_warm_index(sid, timeout_seconds=1)
    assert q["status"] == "queued"
    w2 = ScoutWorker(server.get_tasks())
    assert w2.process_one() is True
    done = server.get_tasks().get(q["task_id"])
    assert done["status"] == "done"


def test_server_error_paths(data_dirs: Path) -> None:
    assert server.get_session("missing")["error"] == "session_not_found"
    assert server.list_sessions()["sessions"] == []
    with pytest.raises(ValueError):
        server.create_project("../x")
    sid = server.create_session()["session_id"]
    assert server.checkout_workspace(sid, "ghost")["error"] == "project_not_found"
    assert server.commit_workspace(sid, "m", ["a"])["error"] == "no_active_workspace"
    assert server.enqueue_ensure_runtime(sid, "go")["error"] == "no_active_workspace"
    assert server.enqueue_warm_index(sid)["error"] == "no_active_workspace"
    assert server._client_for(sid)["error"] == "runtime_not_ready"
    server.create_project("dup")
    assert server.create_project("dup")["error"] == "project_exists"
    assert server.enqueue_import_project("dup", "/tmp")["error"] == "project_exists"
    assert server.enqueue_import_project("../bad", "/tmp")["error"] == "invalid_id"


def test_blast_python_export_rules(tmp_path: Path) -> None:
    class C:
        language_id = "python"
        root = tmp_path

        def is_workspace_loaded(self) -> bool:
            return True

        def document_symbols(self, file_path: str | Path) -> list[SymbolInfo]:
            return [
                SymbolInfo("_priv", 12, 1, 1, str(file_path)),
                SymbolInfo("Pub", 12, 2, 1, str(file_path)),
            ]

        def references(self, *a: Any, **k: Any) -> list[Any]:
            raise RuntimeError("boom")

    f = tmp_path / "m.py"
    f.write_text("x=1\n", encoding="utf-8")
    res = blast_radius(C(), [str(f), str(tmp_path / "missing.py")])  # type: ignore[arg-type]
    assert res.symbols
    assert any(s.warning for s in res.symbols)


def test_lsp_hover_definition_variants(tmp_path: Path) -> None:
    from agent_lsp import lsp_client as lc

    class FakeTransport(lc._Transport):
        def __init__(self) -> None:
            self.q: list[dict[str, Any]] = []
            self.written: list[dict[str, Any]] = []

        def write_message(self, msg: dict[str, Any]) -> None:
            self.written.append(msg)
            mid = msg.get("id")
            method = msg.get("method")
            if method == "initialize":
                self.q.append({"jsonrpc": "2.0", "id": mid, "result": {}})
            elif method == "textDocument/hover":
                self.q.append(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {"contents": {"value": "doc"}},
                    }
                )
            elif method == "textDocument/definition":
                self.q.append(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {
                            "uri": "file:///x.go",
                            "range": {"start": {"line": 0, "character": 0}},
                        },
                    }
                )
            elif method == "textDocument/references":
                self.q.append({"jsonrpc": "2.0", "id": mid, "result": []})
            elif method == "textDocument/documentSymbol":
                self.q.append(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": [
                            {
                                "name": "Foo",
                                "kind": 12,
                                "range": {"start": {"line": 0, "character": 0}},
                                "selectionRange": {"start": {"line": 0, "character": 0}},
                                "children": [],
                            }
                        ],
                    }
                )
            elif mid is not None:
                self.q.append({"jsonrpc": "2.0", "id": mid, "result": None})

        def read_message(self) -> dict[str, Any]:
            import time

            while not self.q:
                time.sleep(0.005)
            return self.q.pop(0)

        def close(self) -> None:
            return None

    tr = FakeTransport()
    client = LspClient(root=tmp_path, language_id="go", transport=tr)
    client._start_reader()
    client.initialize()
    f = tmp_path / "x.go"
    f.write_text("package x\n", encoding="utf-8")
    assert "doc" in client.hover(f, 1, 1)
    assert client.definition(f, 1, 1)
    assert client.references(f, 1, 1) == []
    assert client.document_symbols(f)
    client._workspace_loaded = True
    assert client.is_workspace_loaded()
    client.shutdown()


def test_wait_queued_task_parses_artifact(data_dirs: Path) -> None:
    import asyncio

    from fastmcp.dependencies import Progress

    tid = server.get_tasks().submit("s", "/w", "warm_index")
    server.get_tasks().update(
        tid, status="done", artifact=json.dumps({"session_id": "s", "indexed": True})
    )

    async def run() -> dict[str, Any]:
        return await server._wait_queued_task(tid, Progress())

    row = asyncio.run(run())
    assert row.get("indexed") is True or row.get("status") == "done"
