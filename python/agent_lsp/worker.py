"""Background scout worker: claim_next → import / ensure_runtime / warm_index."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, cast

from agent_lsp._tasks import TaskStore

logger = logging.getLogger(__name__)

POLL_SECONDS = float(os.environ.get("AGENT_LSP_WORKER_POLL_SECONDS", "0.5"))
SCOUT_TARGETS = frozenset({"import_project", "ensure_runtime", "warm_index"})


def _as_task(row: object) -> dict[str, Any]:
    return cast(dict[str, Any], dict(row))  # type: ignore[arg-type]


class ScoutWorker:
    """Poll TaskStore and run long scout pipeline steps."""

    def __init__(self, tasks: TaskStore, *, poll_seconds: float = POLL_SECONDS) -> None:
        self._tasks = tasks
        self._poll = poll_seconds
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def wake(self) -> None:
        self._wake.set()

    def start_daemon(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="agent-lsp-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def process_one(self) -> bool:
        claimed = self._tasks.claim_next()
        if claimed is None:
            return False
        task = _as_task(claimed)
        self._run_task(task)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.process_one()
            except Exception:
                logger.exception("worker iteration failed")
                worked = False
            if worked:
                continue
            self._wake.wait(timeout=self._poll)
            self._wake.clear()

    def _payload(self, task: dict[str, Any]) -> dict[str, Any]:
        raw = task.get("artifact") or "{}"
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _run_task(self, task: dict[str, Any]) -> None:
        tid = task["task_id"]
        target = task["target"]
        if target not in SCOUT_TARGETS:
            self._tasks.update(tid, status="error", error=f"unsupported target: {target}")
            return
        try:
            if target == "import_project":
                self._import_project(tid, task)
            elif target == "ensure_runtime":
                self._ensure_runtime(tid, task)
            else:
                self._warm_index(tid, task)
        except Exception as exc:  # noqa: BLE001
            logger.exception("task %s failed", tid)
            self._tasks.update(tid, status="error", error=str(exc))

    def _import_project(self, tid: str, task: dict[str, Any]) -> None:
        from agent_lsp.paths import project_bare_path
        from agent_lsp_git import GitService

        payload = self._payload(task)
        project_id = str(payload.get("project_id") or "")
        source = str(payload.get("source") or "")
        if not project_id or not source:
            self._tasks.update(tid, status="error", error="missing project_id/source")
            return
        bare = project_bare_path(project_id)
        if bare.exists():
            self._tasks.update(tid, status="error", error=f"project_exists: {project_id}")
            return
        git = GitService()
        src = Path(source)
        if src.exists():
            path = git.import_local(str(src.resolve()), str(bare))
        else:
            path = git.clone_bare(source, str(bare))
        result = json.dumps({"project_id": project_id, "bare": path, "source": source})
        self._tasks.update(tid, status="done", artifact=result, logs="import_project ok")

    def _ensure_runtime(self, tid: str, task: dict[str, Any]) -> None:
        from agent_lsp import server
        from agent_lsp.runtime_hub import HUB

        payload = self._payload(task)
        session_id = str(task.get("session_id") or "")
        language = str(payload.get("language") or "")
        prefer_container = bool(payload.get("prefer_container", True))
        if not session_id or not language:
            self._tasks.update(tid, status="error", error="missing session_id/language")
            return
        bound = server._active_workspace(session_id)
        if isinstance(bound, dict):
            self._tasks.update(tid, status="error", error=json.dumps(bound))
            return
        _, ws = bound
        workspace = Path(ws["path"])
        docker = server.get_docker() if prefer_container else None
        if docker is not None:
            try:
                rt = HUB.ensure_container(session_id, workspace, language, docker)
            except Exception as exc:  # noqa: BLE001
                rt = HUB.ensure_local(session_id, workspace, language)
                self._tasks.update(tid, logs=f"container fallback: {exc}")
        else:
            rt = HUB.ensure_local(session_id, workspace, language)
        server.get_state().bind_container(
            session_id,
            rt.container_id or "unknown",
            image=language,
            language=language,
            host_port=rt.host_port,
            runtime_mode=rt.runtime_mode,
        )
        server.get_state().set_index_status(session_id, "warming")
        result = {
            "session_id": session_id,
            "language": language,
            "runtime_mode": rt.runtime_mode,
            "container_id": rt.container_id,
            "host_port": rt.host_port,
            "index_status": "warming",
        }
        self._tasks.update(tid, status="done", artifact=json.dumps(result))

    def _warm_index(self, tid: str, task: dict[str, Any]) -> None:
        from agent_lsp import server
        from agent_lsp.runtime_hub import HUB

        payload = self._payload(task)
        session_id = str(task.get("session_id") or "")
        timeout = float(payload.get("timeout_seconds") or 120.0)
        if not session_id:
            self._tasks.update(tid, status="error", error="missing session_id")
            return
        rt = HUB.warm(session_id, timeout=timeout)
        server.get_state().set_index_status(session_id, rt.index_status)
        result = {
            "session_id": session_id,
            "index_status": rt.index_status,
            "indexed": True,
            "language": rt.language,
            "runtime_mode": rt.runtime_mode,
            "error": rt.error,
        }
        self._tasks.update(tid, status="done", artifact=json.dumps(result))


_worker: ScoutWorker | None = None
_worker_lock = threading.Lock()


def wake_worker(tasks: TaskStore) -> ScoutWorker:
    """Ensure a daemon worker is running and wake it."""
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = ScoutWorker(tasks)
            _worker.start_daemon()
        else:
            # Keep worker bound to latest store handle.
            _worker._tasks = tasks
        _worker.wake()
        return _worker
