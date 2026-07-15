"""Tests for path containment and bugbot/security fixes."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_lsp.blast import _looks_exported, uri_to_path
from agent_lsp.lsp_client import SymbolInfo
from agent_lsp.paths import resolve_under_root
from agent_lsp.runtime_hub import RuntimeHub, SessionRuntime


def test_resolve_under_root_ok(tmp_path: Path) -> None:
    f = tmp_path / "src" / "a.py"
    f.parent.mkdir()
    f.write_text("x=1\n", encoding="utf-8")
    assert resolve_under_root(tmp_path, "src/a.py") == f.resolve()
    assert resolve_under_root(tmp_path, f) == f.resolve()


def test_resolve_under_root_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        resolve_under_root(tmp_path, "../outside")
    outside = tmp_path.parent / "secret"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_under_root(tmp_path, str(outside))


def test_looks_exported_filters_private() -> None:
    assert _looks_exported(SymbolInfo("Foo", 12, 1, 1, "a.go"), "go")
    assert not _looks_exported(SymbolInfo("bar", 12, 1, 1, "a.go"), "go")
    assert not _looks_exported(SymbolInfo("_priv", 12, 1, 1, "a.py"), "python")
    assert _looks_exported(SymbolInfo("pub", 12, 1, 1, "a.py"), "python")
    assert not _looks_exported(SymbolInfo("x", 1, 1, 1, "a.py"), "python")  # kind not exported


def test_uri_to_path_decodes() -> None:
    assert " " in uri_to_path("file:///tmp/my%20file.py") or "%20" not in uri_to_path(
        "file:///tmp/my%20file.py"
    )


def test_warm_error_when_no_seed(tmp_path: Path) -> None:
    hub = RuntimeHub()
    client = type(
        "C",
        (),
        {
            "wait_until_ready": lambda self, timeout=120.0: False,
            "document_symbols": lambda self, p: [],
            "_workspace_loaded": False,
        },
    )()
    hub.put(
        SessionRuntime(
            session_id="s",
            workspace_path=tmp_path,
            language="python",
            runtime_mode="local",
            client=client,  # type: ignore[arg-type]
        )
    )
    rt = hub.warm("s", timeout=0.05)
    assert rt.index_status == "error"


def test_ensure_local_rejects_container_reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_LSP_ALLOW_LOCAL", "1")
    hub = RuntimeHub()
    stopped: list[str] = []

    class FakeDocker:
        def stop(self, cid: str) -> None:
            stopped.append(f"stop:{cid}")

        def remove(self, cid: str) -> None:
            stopped.append(f"remove:{cid}")

    class DummyClient:
        def __init__(self, *a: object, **k: object) -> None:
            self._workspace_loaded = False

        @classmethod
        def spawn_local(
            cls,
            root: Path,
            language_id: str,
            cmd: list[str],
            *,
            settings: object | None = None,
        ) -> DummyClient:
            return cls()

        def shutdown(self) -> None:
            return None

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
                "local_cmd": ["true"],
                "container_workdir": "/workspace",
            },
        )(),
    )
    hub.put(
        SessionRuntime(
            session_id="sx",
            workspace_path=tmp_path,
            language="python",
            runtime_mode="container",
            container_id="ctr-1",
            client=DummyClient(),  # type: ignore[arg-type]
        )
    )
    rt = hub.ensure_local("sx", tmp_path, "python", docker=FakeDocker())
    assert rt.runtime_mode == "local"
    assert "stop:ctr-1" in stopped
    assert "remove:ctr-1" in stopped


def test_blast_rejects_escaped_paths(tmp_path: Path) -> None:
    from agent_lsp.blast import blast_radius

    class C:
        language_id = "python"
        root = tmp_path

        def is_workspace_loaded(self) -> bool:
            return True

        def document_symbols(self, file_path: object) -> list[object]:
            return []

        def references(self, *a: object, **k: object) -> list[object]:
            return []

    with pytest.raises(ValueError, match="escapes workspace"):
        blast_radius(C(), ["../outside.py"])  # type: ignore[arg-type]


def test_blast_reports_skipped_missing(tmp_path: Path) -> None:
    from agent_lsp.blast import blast_radius, blast_to_dict
    from agent_lsp.lsp_client import SymbolInfo

    f = tmp_path / "ok.py"
    f.write_text("def Foo():\n    pass\n", encoding="utf-8")

    class C:
        language_id = "python"
        root = tmp_path

        def is_workspace_loaded(self) -> bool:
            return True

        def document_symbols(self, file_path: object) -> list[SymbolInfo]:
            return [SymbolInfo("Foo", 12, 1, 1, str(file_path))]

        def references(self, *a: object, **k: object) -> list[object]:
            return []

    res = blast_radius(C(), [str(f), str(tmp_path / "missing.py")])  # type: ignore[arg-type]
    assert res.changed_files == [str(f)]
    assert res.skipped_files == [str(tmp_path / "missing.py")]
    d = blast_to_dict(res)
    assert d["skipped_files"] == res.skipped_files


def test_warm_index_task_errors_when_index_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_lsp.worker import ScoutWorker
    from agent_lsp._tasks import TaskStore
    import agent_lsp.runtime_hub as rh
    from agent_lsp import server

    store = TaskStore(str(tmp_path / "tasks.db"))
    hub = RuntimeHub()
    client = type(
        "C",
        (),
        {
            "wait_until_ready": lambda self, timeout=120.0: False,
            "document_symbols": lambda self, p: [],
            "_workspace_loaded": False,
            "language": "python",
            "runtime_mode": "local",
            "error": None,
        },
    )()
    # warm() mutates SessionRuntime fields on the hub entry
    hub.put(
        SessionRuntime(
            session_id="s-warm",
            workspace_path=tmp_path,
            language="python",
            runtime_mode="local",
            client=client,  # type: ignore[arg-type]
        )
    )
    monkeypatch.setattr(rh, "HUB", hub)

    class FakeState:
        def set_index_status(self, session_id: str, status: str) -> None:
            self.last = (session_id, status)

    monkeypatch.setattr(server, "get_state", lambda: FakeState())
    tid = store.submit("s-warm", str(tmp_path), "warm_index", '{"timeout_seconds": 0.05}')
    w = ScoutWorker(store)
    assert w.process_one() is True
    row = store.get(tid)
    assert row["status"] == "error"
    assert row["artifact"] is not None
    assert '"indexed": false' in row["artifact"] or '"indexed":false' in row["artifact"]


def test_reclaim_stale_tasks(tmp_path: Path) -> None:
    from agent_lsp._tasks import TaskStore

    store = TaskStore(str(tmp_path / "t.db"))
    tid = store.submit("s", "/w", "warm_index")
    claimed = store.claim_next()
    assert claimed["status"] == "running"
    assert store.reclaim_stale(0) == 1
    assert store.get(tid)["status"] == "queued"
    again = store.claim_next()
    assert again["task_id"] == tid

