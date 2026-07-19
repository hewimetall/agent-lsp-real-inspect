"""Hot-swap after install_workspace_deps (force recycle / dead transport)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest

pytest.importorskip("agent_lsp._tasks")
pytest.importorskip("agent_lsp_state")
pytest.importorskip("agent_lsp_git")

from agent_lsp import paths as paths_mod
from agent_lsp import server
from agent_lsp._tasks import TaskStore
from agent_lsp.runtime_hub import RuntimeHub, SessionRuntime
from agent_lsp.worker import ScoutWorker


@pytest.fixture()
def data_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
    server._docker_error = None
    monkeypatch.setenv("AGENT_LSP_ALLOW_LOCAL", "1")
    return tmp_path


def _session_with_workspace(tmp_path: Path) -> tuple[str, Path]:
    sid = server.create_session()["session_id"]
    server.create_project("hotswap")
    co = server.checkout_workspace(sid, "hotswap")
    wt = Path(co["path"])
    (wt / "app.py").write_text("x = 1\n", encoding="utf-8")
    (wt / "requirements.txt").write_text("requests\n", encoding="utf-8")
    return sid, wt


@pytest.fixture(autouse=True)
def _no_daemon_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep enqueue from starting a background worker during unit tests."""
    monkeypatch.setattr(
        "agent_lsp.worker.wake_worker", lambda tasks: ScoutWorker(tasks)  # type: ignore[arg-type]
    )
    monkeypatch.setattr(server, "wake_worker", lambda tasks: ScoutWorker(tasks))  # type: ignore[arg-type]


def test_hot_swap_force_recycles_container(
    data_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_lsp.runtime_hub as rh
    from agent_lsp import env_layout

    started: list[str] = []
    stopped: list[str] = []

    class FakeDocker:
        def run(self, *a: Any, **k: Any) -> dict[str, Any]:
            ws = Path(str(k.get("binds", [""])[0]).split(":")[0])
            env_layout.ensure_agent_lsp_dir(ws)
            venv = env_layout.venv_path(ws)
            (venv / "lib" / "python3.12" / "site-packages").mkdir(parents=True, exist_ok=True)
            (venv / "bin").mkdir(parents=True, exist_ok=True)
            (venv / "bin" / "python").write_text("", encoding="utf-8")
            return {"status_code": 0, "logs": "pip ok", "container_id": "install-1"}

        def start_persistent(self, *a: Any, **k: Any) -> dict[str, Any]:
            cid = f"lsp-{len(started) + 1}"
            started.append(cid)
            return {"container_id": cid, "host_port": 37000 + len(started)}

        def stop(self, cid: str) -> None:
            stopped.append(cid)

        def remove(self, cid: str) -> None:
            stopped.append(f"rm:{cid}")

        def is_running(self, cid: str) -> bool:
            return True

    class DummyClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            self._workspace_loaded = False
            self.uri_root = Path("/workspace")
            self.language_id = "python"

        @classmethod
        def connect_tcp(cls, *a: Any, **k: Any) -> DummyClient:
            return cls()

        def transport_alive(self) -> bool:
            return True

        def apply_settings(self, settings: Any) -> None:
            return None

        def shutdown(self) -> None:
            return None

    docker = FakeDocker()
    hub = RuntimeHub()
    monkeypatch.setattr(rh, "HUB", hub)
    monkeypatch.setattr(server, "HUB", hub)
    monkeypatch.setattr(server, "get_docker", lambda: docker)
    monkeypatch.setattr("agent_lsp.runtime_hub.LspClient", DummyClient)
    monkeypatch.setattr(
        "agent_lsp.runtime_hub.get_runtime",
        lambda language: type(
            "R",
            (),
            {
                "language": language,
                "image": "img:py",
                "cmd": ["true"],
                "local_cmd": ["true"],
                "container_workdir": "/workspace",
            },
        )(),
    )
    monkeypatch.setattr("agent_lsp.runtime_hub.resolve_image", lambda *a, **k: "img:py")
    monkeypatch.setattr(
        "agent_lsp.runtime_hub.build_lsp_settings", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        "agent_lsp.runtime_hub.build_initialization_options", lambda *a, **k: {}
    )

    sid, wt = _session_with_workspace(data_dirs)
    hub.ensure_container(sid, wt, "python", docker, image_override="img:py")
    assert len(started) == 1
    first_cid = hub.get(sid).container_id  # type: ignore[union-attr]

    q = server.enqueue_install_workspace_deps(
        sid,
        language="python",
        language_version="3.12",
        packages=["requests"],
        restart_runtime=True,
    )
    w = ScoutWorker(server.get_tasks(), poll_seconds=0.01)
    assert w.process_one() is True
    st = server.get_task_status(q["task_id"])
    assert st["status"] == "done"
    art = json.loads(st["artifact"])
    assert art["restarted_runtime"] is True
    assert len(started) == 2
    assert hub.get(sid).container_id != first_cid  # type: ignore[union-attr]
    assert first_cid in stopped


def test_hot_swap_recycle_failure_marks_needs_recycle(
    data_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_lsp.runtime_hub as rh
    from agent_lsp import env_layout

    class FakeDocker:
        def run(self, *a: Any, **k: Any) -> dict[str, Any]:
            ws = Path(str(k.get("binds", [""])[0]).split(":")[0])
            env_layout.ensure_agent_lsp_dir(ws)
            return {"status_code": 0, "logs": "ok", "container_id": "i1"}

        def start_persistent(self, *a: Any, **k: Any) -> dict[str, Any]:
            raise RuntimeError("cannot start replacement")

        def stop(self, cid: str) -> None:
            return None

        def remove(self, cid: str) -> None:
            return None

        def is_running(self, cid: str) -> bool:
            return True

    class AliveClient:
        def __init__(self) -> None:
            self._workspace_loaded = False
            self.uri_root = Path("/workspace")
            self.language_id = "python"

        def transport_alive(self) -> bool:
            return True

        def shutdown(self) -> None:
            return None

    hub = RuntimeHub()
    monkeypatch.setattr(rh, "HUB", hub)
    monkeypatch.setattr(server, "HUB", hub)
    monkeypatch.setattr(server, "get_docker", lambda: FakeDocker())

    sid, wt = _session_with_workspace(data_dirs)
    hub.put(
        SessionRuntime(
            session_id=sid,
            workspace_path=wt,
            language="python",
            runtime_mode="container",
            container_id="old-ctr",
            host_port=37001,
            client=AliveClient(),  # type: ignore[arg-type]
            language_version="3.12",
            image="img:py",
        )
    )

    q = server.enqueue_install_workspace_deps(
        sid, language="python", packages=["x"], restart_runtime=True
    )
    w = ScoutWorker(server.get_tasks(), poll_seconds=0.01)
    assert w.process_one() is True
    st = server.get_task_status(q["task_id"])
    assert st["status"] == "error"
    assert "needs_recycle" in (st.get("error") or "")
    rt = hub.get(sid)
    assert rt is not None
    assert rt.needs_recycle is True
    assert rt.container_id == "old-ctr"


def test_soft_path_marks_stale_when_transport_dead(
    data_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_lsp.runtime_hub as rh
    from agent_lsp import env_layout

    class FakeDocker:
        def run(self, *a: Any, **k: Any) -> dict[str, Any]:
            ws = Path(str(k.get("binds", [""])[0]).split(":")[0])
            env_layout.ensure_agent_lsp_dir(ws)
            return {"status_code": 0, "logs": "ok", "container_id": "i1"}

    class DeadClient:
        def __init__(self) -> None:
            self._workspace_loaded = False
            self.uri_root = Path("/workspace")
            self.language_id = "python"

        def transport_alive(self) -> bool:
            return False

        def apply_settings(self, settings: Any) -> None:
            raise AssertionError("should not refresh dead transport")

        def shutdown(self) -> None:
            return None

    hub = RuntimeHub()
    monkeypatch.setattr(rh, "HUB", hub)
    monkeypatch.setattr(server, "HUB", hub)
    monkeypatch.setattr(server, "get_docker", lambda: FakeDocker())

    sid, wt = _session_with_workspace(data_dirs)
    hub.put(
        SessionRuntime(
            session_id=sid,
            workspace_path=wt,
            language="python",
            runtime_mode="container",
            container_id="dead-ctr",
            client=DeadClient(),  # type: ignore[arg-type]
        )
    )

    q = server.enqueue_install_workspace_deps(
        sid, language="python", packages=["x"], restart_runtime=False
    )
    w = ScoutWorker(server.get_tasks(), poll_seconds=0.01)
    assert w.process_one() is True
    st = server.get_task_status(q["task_id"])
    assert st["status"] == "done"
    art = json.loads(st["artifact"])
    assert art.get("runtime_stale") is True
    assert art.get("restarted_runtime") is False
    rt = hub.get(sid)
    assert rt is not None
    assert rt.needs_recycle is True
    assert rt.client is None


def test_soft_path_refresh_settings_when_alive(
    data_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import agent_lsp.runtime_hub as rh
    from agent_lsp import env_layout

    refreshed: list[str] = []

    class FakeDocker:
        def run(self, *a: Any, **k: Any) -> dict[str, Any]:
            ws = Path(str(k.get("binds", [""])[0]).split(":")[0])
            env_layout.ensure_agent_lsp_dir(ws)
            return {"status_code": 0, "logs": "ok", "container_id": "i1"}

    class AliveClient:
        def __init__(self) -> None:
            self._workspace_loaded = False
            self.uri_root = Path("/workspace")
            self.language_id = "python"
            self.root = Path(".")

        def transport_alive(self) -> bool:
            return True

        def apply_settings(self, settings: Any) -> None:
            refreshed.append("ok")

        def shutdown(self) -> None:
            return None

    hub = RuntimeHub()
    monkeypatch.setattr(rh, "HUB", hub)
    monkeypatch.setattr(server, "HUB", hub)
    monkeypatch.setattr(server, "get_docker", lambda: FakeDocker())
    monkeypatch.setattr(
        "agent_lsp.runtime_hub.build_lsp_settings", lambda *a, **k: {"python": {}}
    )

    sid, wt = _session_with_workspace(data_dirs)
    hub.put(
        SessionRuntime(
            session_id=sid,
            workspace_path=wt,
            language="python",
            runtime_mode="container",
            container_id="alive-ctr",
            client=AliveClient(),  # type: ignore[arg-type]
        )
    )

    q = server.enqueue_install_workspace_deps(
        sid, language="python", packages=["x"], restart_runtime=False
    )
    w = ScoutWorker(server.get_tasks(), poll_seconds=0.01)
    assert w.process_one() is True
    assert server.get_task_status(q["task_id"])["status"] == "done"
    assert refreshed == ["ok"]


def test_ensure_local_force_hot_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_LSP_ALLOW_LOCAL", "1")
    hub = RuntimeHub()
    clients: list[Any] = []

    class DummyClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            self._workspace_loaded = False
            clients.append(self)

        @classmethod
        def spawn_local(cls, *a: Any, **k: Any) -> DummyClient:
            return cls()

        def transport_alive(self) -> bool:
            return True

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
    monkeypatch.setattr(
        "agent_lsp.runtime_hub.build_lsp_settings", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        "agent_lsp.runtime_hub.build_initialization_options", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        "agent_lsp.runtime_hub.resolve_lsp_command", lambda cmd: cmd
    )

    first = hub.ensure_local("s-local", tmp_path, "python")
    reused = hub.ensure_local("s-local", tmp_path, "python")
    assert reused.client is first.client
    forced = hub.ensure_local("s-local", tmp_path, "python", force=True)
    assert forced.client is not first.client
    assert len(clients) == 2
