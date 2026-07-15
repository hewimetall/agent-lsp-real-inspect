"""Tests for path containment and bugbot/security fixes."""

from __future__ import annotations

import json
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


def test_ensure_local_rejects_container_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
            initialization_options: object | None = None,
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
    import agent_lsp.runtime_hub as rh
    from agent_lsp import server
    from agent_lsp._tasks import TaskStore
    from agent_lsp.worker import ScoutWorker

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


def test_needs_recycle_blocks_reuse_and_warm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = RuntimeHub()
    started: list[str] = []

    class FakeDocker:
        def start_persistent(self, *a: object, **k: object) -> dict[str, object]:
            started.append("x")
            return {"container_id": f"cid-{len(started)}", "host_port": 41000 + len(started)}

        def stop(self, cid: str) -> None:
            return None

        def remove(self, cid: str) -> None:
            return None

        def is_running(self, cid: str) -> bool:
            return True

    class DummyClient:
        def __init__(self, *a: object, **k: object) -> None:
            self._workspace_loaded = False

        @classmethod
        def connect_tcp(cls, *a: object, **k: object) -> DummyClient:
            return cls()

        def wait_until_ready(self, timeout: float = 120.0) -> bool:
            return True

        def document_symbols(self, file_path: object) -> list[object]:
            return []

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
                "image": "img:1",
                "cmd": ["true"],
                "local_cmd": ["true"],
                "container_workdir": "/workspace",
            },
        )(),
    )
    monkeypatch.setattr(
        "agent_lsp.runtime_hub.resolve_image", lambda *a, **k: "img:1"
    )
    docker = FakeDocker()
    first = hub.ensure_container("s-stale", tmp_path, "python", docker, image_override="img:1")
    first.needs_recycle = True
    warmed = hub.warm("s-stale", timeout=0.05)
    assert warmed.index_status == "error"
    assert "needs recycle" in (warmed.error or "")
    recycled = hub.ensure_container(
        "s-stale", tmp_path, "python", docker, image_override="img:1"
    )
    assert recycled.container_id != first.container_id
    assert recycled.needs_recycle is False
    assert len(started) == 2

    monkeypatch.delenv("AGENT_LSP_ALLOW_LOCAL", raising=False)
    hub = RuntimeHub()
    with pytest.raises(RuntimeError, match="local LSP runtimes are disabled"):
        hub.ensure_local("s", tmp_path, "python")


def test_ensure_container_recycles_when_docker_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = RuntimeHub()
    started: list[str] = []
    running: dict[str, bool] = {}

    class FakeDocker:
        def start_persistent(self, *a: object, **k: object) -> dict[str, object]:
            started.append("x")
            cid = f"cid-{len(started)}"
            running[cid] = True
            return {"container_id": cid, "host_port": 42000 + len(started)}

        def stop(self, cid: str) -> None:
            running[cid] = False

        def remove(self, cid: str) -> None:
            running.pop(cid, None)

        def is_running(self, cid: str) -> bool:
            return bool(running.get(cid, False))

    class DummyClient:
        def __init__(self, *a: object, **k: object) -> None:
            self._workspace_loaded = False

        @classmethod
        def connect_tcp(cls, *a: object, **k: object) -> DummyClient:
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
                "image": "img:1",
                "cmd": ["true"],
                "local_cmd": ["true"],
                "container_workdir": "/workspace",
            },
        )(),
    )
    monkeypatch.setattr(
        "agent_lsp.runtime_hub.resolve_image", lambda *a, **k: "img:1"
    )
    docker = FakeDocker()
    first = hub.ensure_container("s-dead", tmp_path, "python", docker, image_override="img:1")
    assert first.container_id is not None
    running[first.container_id] = False
    second = hub.ensure_container("s-dead", tmp_path, "python", docker, image_override="img:1")
    assert second.container_id != first.container_id
    assert len(started) == 2
    assert first.needs_recycle is True
    assert first.index_status == "stale"


def test_ensure_container_force_recycles_same_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = RuntimeHub()
    started: list[str] = []
    stopped: list[str] = []

    class FakeDocker:
        def start_persistent(self, *a: object, **k: object) -> dict[str, object]:
            name = str(k.get("name") or "c")
            started.append(name)
            return {"container_id": f"cid-{len(started)}", "host_port": 40000 + len(started)}

        def stop(self, cid: str) -> None:
            stopped.append(cid)

        def remove(self, cid: str) -> None:
            stopped.append(f"rm:{cid}")

        def is_running(self, cid: str) -> bool:
            return True

    class DummyClient:
        def __init__(self, *a: object, **k: object) -> None:
            self._workspace_loaded = False

        @classmethod
        def connect_tcp(cls, *a: object, **k: object) -> DummyClient:
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
                "image": "img:1",
                "cmd": ["true"],
                "local_cmd": ["true"],
                "container_workdir": "/workspace",
            },
        )(),
    )
    monkeypatch.setattr(
        "agent_lsp.runtime_hub.resolve_image", lambda *a, **k: "img:1"
    )
    docker = FakeDocker()
    first = hub.ensure_container("s-force", tmp_path, "python", docker, image_override="img:1")
    reused = hub.ensure_container("s-force", tmp_path, "python", docker, image_override="img:1")
    assert reused.container_id == first.container_id
    assert len(started) == 1
    forced = hub.ensure_container(
        "s-force", tmp_path, "python", docker, image_override="img:1", force=True
    )
    assert forced.container_id != first.container_id
    assert len(started) == 2
    assert first.container_id in stopped


def test_run_script_fail_closed_without_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_lsp import server
    from agent_lsp._tasks import TaskStore
    from agent_lsp.worker import ScoutWorker

    monkeypatch.delenv("AGENT_LSP_ALLOW_LOCAL", raising=False)
    monkeypatch.setattr(server, "get_docker", lambda: None)
    w = ScoutWorker(TaskStore(str(tmp_path / "t.db")))
    out = w._run_script(workspace=tmp_path, image="python:3.12-bookworm", script="true")
    assert out["mode"] == "error"
    assert "Docker unavailable" in str(out["logs"])


def test_ensure_runtime_ignores_prefer_local_without_allow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prefer_container=false must not escape to host when ALLOW_LOCAL is off."""
    import agent_lsp.runtime_hub as rh
    from agent_lsp import paths as paths_mod
    from agent_lsp import server
    from agent_lsp._tasks import TaskStore
    from agent_lsp.worker import ScoutWorker

    monkeypatch.delenv("AGENT_LSP_ALLOW_LOCAL", raising=False)
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
    monkeypatch.setattr(server, "get_docker", lambda: None)
    monkeypatch.setattr(server, "wake_worker", lambda tasks: None)

    store = TaskStore(str(tmp_path / "tasks.db"))
    monkeypatch.setattr(server, "get_tasks", lambda: store)
    sid = server.create_session()["session_id"]
    server.create_project("p1")
    co = server.checkout_workspace(sid, "p1")
    tid = store.submit(
        sid,
        co["path"],
        "ensure_runtime",
        json.dumps({"language": "python", "prefer_container": False}),
    )
    w = ScoutWorker(store)
    assert w.process_one() is True
    row = store.get(tid)
    assert row["status"] == "error"
    assert "Docker unavailable" in (row.get("error") or "")
    assert rh.HUB.get(sid) is None

