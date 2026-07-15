"""TaskStore + worker + task_bridge tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("agent_lsp._tasks")
pytest.importorskip("agent_lsp_state")
pytest.importorskip("agent_lsp_git")

from agent_lsp import paths as paths_mod
from agent_lsp import server
from agent_lsp._tasks import TaskStore
from agent_lsp.task_bridge import await_sqlite_task, status_message
from agent_lsp.worker import ScoutWorker, wake_worker


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
    server._docker_error = "disabled-in-tests"
    return tmp_path


def test_taskstore_submit_claim_done(tmp_path: Path) -> None:
    store = TaskStore(str(tmp_path / "tasks.db"))
    tid = store.submit("s1", "/ws", "warm_index")
    row = store.get(tid)
    assert row["status"] == "queued"
    claimed = store.claim_next()
    assert claimed["task_id"] == tid
    assert claimed["status"] == "running"
    store.update(tid, status="done", artifact='{"ok":true}', logs="fine")
    done = store.get(tid)
    assert done["status"] == "done"
    latest = store.find_latest_done("/ws")
    assert latest["task_id"] == tid


def test_status_message_variants() -> None:
    assert "status=queued" in status_message(
        {"task_id": "t", "status": "queued", "error": None}
    )
    assert "status=done" in status_message({"task_id": "t", "status": "done"})
    assert "error=boom" in status_message(
        {"task_id": "t", "status": "error", "error": "boom"}
    )
    long = "x" * 400
    msg = status_message({"task_id": "t", "status": "error", "error": long})
    assert "..." in msg


def test_await_sqlite_task_done(tmp_path: Path) -> None:
    store = TaskStore(str(tmp_path / "t.db"))
    tid = store.submit("s", "/w", "warm_index")
    store.update(tid, status="done", artifact="{}")

    class Prog:
        def __init__(self) -> None:
            self.msgs: list[str] = []

        async def set_message(self, message: str | None) -> None:
            if message:
                self.msgs.append(message)

    prog = Prog()
    row = asyncio.run(await_sqlite_task(store, tid, prog, poll_seconds=0.01, timeout=2))
    assert row["status"] == "done"
    assert prog.msgs


def test_await_missing_and_timeout(tmp_path: Path) -> None:
    store = TaskStore(str(tmp_path / "t.db"))
    with pytest.raises(LookupError):
        asyncio.run(await_sqlite_task(store, "missing", None, poll_seconds=0.01, timeout=0.2))
    tid = store.submit("s", "/w", "warm_index")
    with pytest.raises(TimeoutError):
        asyncio.run(await_sqlite_task(store, tid, None, poll_seconds=0.01, timeout=0.15))


def test_worker_import_and_warm_flow(data_dirs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_lsp import worker as worker_mod

    monkeypatch.setenv("AGENT_LSP_ALLOW_LOCAL", "1")

    if worker_mod._worker is not None:
        worker_mod._worker.stop()
        worker_mod._worker = None

    def _no_wake(tasks: object) -> ScoutWorker:
        return ScoutWorker(tasks)  # type: ignore[arg-type]

    monkeypatch.setattr(worker_mod, "wake_worker", _no_wake)
    monkeypatch.setattr(server, "wake_worker", _no_wake)

    sid = server.create_session()["session_id"]
    server.create_project("demo")
    co = server.checkout_workspace(sid, "demo")
    wt = Path(co["path"])
    (wt / "main.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    server.commit_workspace(sid, "add main", ["main.py"])

    queued = server.enqueue_import_project("copied", str(wt))
    assert queued["status"] == "queued"
    # Debug if still empty
    row = server.get_tasks().get(queued["task_id"])
    assert row is not None, queued
    assert row["status"] == "queued"
    worker = ScoutWorker(server.get_tasks(), poll_seconds=0.05)
    assert worker.process_one() is True
    row = server.get_task_status(queued["task_id"])
    assert row["status"] == "done"

    q2 = server.enqueue_ensure_runtime(sid, "python", prefer_container=False)
    worker2 = ScoutWorker(server.get_tasks(), poll_seconds=0.05)
    worker2.process_one()
    st = server.get_task_status(q2["task_id"])
    assert st["status"] in {"done", "error"}


def test_worker_install_deps_local(data_dirs: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_lsp import worker as worker_mod
    from agent_lsp import env_layout

    if worker_mod._worker is not None:
        worker_mod._worker.stop()
        worker_mod._worker = None

    monkeypatch.setattr(worker_mod, "wake_worker", lambda tasks: ScoutWorker(tasks))  # type: ignore[arg-type]
    monkeypatch.setattr(server, "wake_worker", lambda tasks: ScoutWorker(tasks))  # type: ignore[arg-type]

    sid = server.create_session()["session_id"]
    server.create_project("depsdemo")
    co = server.checkout_workspace(sid, "depsdemo")
    wt = Path(co["path"])
    (wt / "app.py").write_text("x = 1\n", encoding="utf-8")

    def fake_run(self, **kwargs):  # noqa: ANN001
        env_layout.ensure_agent_lsp_dir(Path(kwargs["workspace"]))
        venv = env_layout.venv_path(Path(kwargs["workspace"]))
        (venv / "lib" / "python3.12" / "site-packages").mkdir(parents=True, exist_ok=True)
        (venv / "bin").mkdir(parents=True, exist_ok=True)
        py = venv / "bin" / "python"
        if not py.exists():
            py.write_text("", encoding="utf-8")
        return {
            "mode": "local",
            "image": None,
            "status_code": 0,
            "logs": "ok",
            "container_id": None,
        }

    monkeypatch.setattr(ScoutWorker, "_run_script", fake_run)

    q = server.enqueue_install_workspace_deps(
        sid,
        language="python",
        language_version="3.12",
        packages=["requests"],
        restart_runtime=False,
    )
    worker = ScoutWorker(server.get_tasks(), poll_seconds=0.05)
    assert worker.process_one() is True
    st = server.get_task_status(q["task_id"])
    assert st["status"] == "done"
    art = json.loads(st.get("artifact") or "{}")
    assert art.get("manager") == "pip"
    assert art.get("site_packages")

    q_apt = server.enqueue_install_apt_packages(sid, ["ca-certificates"], language="python")
    assert worker.process_one() is True
    apt_st = server.get_task_status(q_apt["task_id"])
    assert apt_st["status"] == "done"
    assert "ca-certificates" in env_layout.read_apt_packages(wt)

