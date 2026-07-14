"""Session runtimes — hold containers (or local LSP) and warm clients."""

from __future__ import annotations

import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_lsp.lsp_client import LspClient, resolve_lsp_command
from agent_lsp.runtimes import LanguageRuntime, get_runtime


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class SessionRuntime:
    session_id: str
    workspace_path: Path
    language: str
    runtime_mode: str  # container | local
    container_id: str | None = None
    host_port: int | None = None
    client: LspClient | None = None
    index_status: str = "cold"
    error: str | None = None
    local_proc: subprocess.Popen[bytes] | None = None


@dataclass
class RuntimeHub:
    """In-memory hub: session_id → live LSP client / container handles."""

    sessions: dict[str, SessionRuntime] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, session_id: str) -> SessionRuntime | None:
        with self._lock:
            return self.sessions.get(session_id)

    def put(self, rt: SessionRuntime) -> None:
        with self._lock:
            prev = self.sessions.get(rt.session_id)
            self.sessions[rt.session_id] = rt
        if prev is not None and prev is not rt:
            docker = None
            if prev.runtime_mode == "container":
                try:
                    from agent_lsp.server import get_docker

                    docker = get_docker()
                except Exception:
                    docker = None
            self._teardown(prev, docker=docker)

    def drop(self, session_id: str) -> SessionRuntime | None:
        with self._lock:
            return self.sessions.pop(session_id, None)

    def ensure_local(
        self,
        session_id: str,
        workspace: Path,
        language: str,
        docker: Any | None = None,
    ) -> SessionRuntime:
        existing = self.get(session_id)
        if (
            existing
            and existing.client
            and existing.language == language
            and existing.runtime_mode == "local"
        ):
            return existing
        if existing is not None:
            # Always pass docker when replacing a container-backed runtime so stop/remove runs.
            docker_svc = docker
            if docker_svc is None and existing.runtime_mode == "container":
                try:
                    from agent_lsp.server import get_docker

                    docker_svc = get_docker()
                except Exception:
                    docker_svc = None
            self.shutdown(session_id, docker=docker_svc)

        spec = get_runtime(language)
        port = _free_port()
        cmd = resolve_lsp_command([c.replace("{port}", str(port)) for c in spec.local_cmd])
        if any("{port}" in c for c in spec.local_cmd):
            import time

            proc: subprocess.Popen[bytes] = subprocess.Popen(cmd, cwd=str(workspace))
            client = None
            for _ in range(50):
                try:
                    client = LspClient.connect_tcp(workspace, language, "127.0.0.1", port)
                    break
                except Exception:
                    time.sleep(0.1)
            if client is None:
                proc.kill()
                raise RuntimeError(f"failed to connect local LSP on port {port}")
            rt = SessionRuntime(
                session_id=session_id,
                workspace_path=workspace,
                language=language,
                runtime_mode="local",
                container_id=f"local-{proc.pid}",
                host_port=port,
                client=client,
                index_status="warming",
                local_proc=proc,
            )
        else:
            client = LspClient.spawn_local(workspace, language, cmd)
            rt = SessionRuntime(
                session_id=session_id,
                workspace_path=workspace,
                language=language,
                runtime_mode="local",
                container_id=f"local-stdio-{session_id[:8]}",
                host_port=None,
                client=client,
                index_status="warming",
                local_proc=None,
            )
        with self._lock:
            self.sessions[session_id] = rt
        return rt

    def ensure_container(
        self,
        session_id: str,
        workspace: Path,
        language: str,
        docker: Any,
        image_override: str | None = None,
    ) -> SessionRuntime:
        existing = self.get(session_id)
        if (
            existing
            and existing.client
            and existing.language == language
            and existing.runtime_mode == "container"
        ):
            return existing
        if existing is not None:
            self.shutdown(session_id, docker=docker)

        spec: LanguageRuntime = get_runtime(language)
        image = image_override or spec.image
        host_port = _free_port()
        binds = [f"{workspace.resolve()}:{spec.container_workdir}:rw"]
        started = docker.start_persistent(
            image,
            spec.cmd,
            binds=binds,
            workdir=spec.container_workdir,
            env=[],
            host_port=host_port,
            container_port=3737,
            name=f"agent-lsp-{session_id[:8]}-{language}",
        )
        cid = started["container_id"]
        published = started.get("host_port") or host_port

        import time

        client = None
        last_err: Exception | None = None
        for _ in range(80):
            try:
                client = LspClient.connect_tcp(
                    workspace,
                    language,
                    "127.0.0.1",
                    int(published),
                    uri_root=Path(spec.container_workdir),
                )
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(0.15)
        if client is None:
            try:
                docker.stop(cid)
                docker.remove(cid)
            except Exception:
                pass
            raise RuntimeError(f"LSP container not reachable: {last_err}")

        rt = SessionRuntime(
            session_id=session_id,
            workspace_path=workspace,
            language=language,
            runtime_mode="container",
            container_id=cid,
            host_port=int(published),
            client=client,
            index_status="warming",
        )
        with self._lock:
            self.sessions[session_id] = rt
        return rt

    def warm(self, session_id: str, timeout: float = 120.0) -> SessionRuntime:
        rt = self.get(session_id)
        if rt is None or rt.client is None:
            raise RuntimeError(f"no runtime for session {session_id}")
        rt.index_status = "warming"
        rt.error = None
        # Many servers (pyright, gopls) never emit workDoneProgress end. Bound the
        # wait so seed probing can still finish inside the MCP task budget.
        progress_budget = min(15.0, max(3.0, timeout * 0.15))
        ready = rt.client.wait_until_ready(timeout=progress_budget)
        seed = _find_seed_file(rt.workspace_path, rt.language)
        probed = False
        if seed is not None:
            try:
                syms = rt.client.document_symbols(seed)
                if syms:
                    rt.client.references(syms[0].file, syms[0].line, syms[0].character)
                probed = True
            except Exception as exc:  # noqa: BLE001
                rt.error = str(exc)
        if ready or probed:
            rt.index_status = "ready"
            rt.client._workspace_loaded = True
        else:
            rt.index_status = "error"
            if not rt.error:
                rt.error = "index warm timed out with no seed file"
        with self._lock:
            self.sessions[session_id] = rt
        return rt

    def shutdown(self, session_id: str, docker: Any | None = None) -> None:
        rt = self.drop(session_id)
        if rt is None:
            return
        self._teardown(rt, docker=docker)

    def _teardown(self, rt: SessionRuntime, docker: Any | None) -> None:
        if rt.client is not None:
            try:
                rt.client.shutdown()
            except Exception:
                pass
        if rt.local_proc is not None:
            try:
                rt.local_proc.terminate()
                rt.local_proc.wait(timeout=5)
            except Exception:
                try:
                    rt.local_proc.kill()
                except Exception:
                    pass
        if rt.runtime_mode == "container" and rt.container_id and docker is not None:
            try:
                docker.stop(rt.container_id)
                docker.remove(rt.container_id)
            except Exception:
                pass


def _find_seed_file(root: Path, language: str) -> Path | None:
    patterns = {
        "go": ["**/*.go"],
        "python": ["**/*.py"],
        "typescript": ["**/*.{ts,tsx}"],
        "rust": ["**/*.rs"],
    }
    for pattern in patterns.get(language, ["**/*"]):
        if "{ts,tsx}" in pattern:
            cands = list(root.glob("**/*.ts")) + list(root.glob("**/*.tsx"))
        else:
            cands = list(root.glob(pattern))
        for p in cands:
            if p.is_file() and "node_modules" not in p.parts and "target" not in p.parts:
                return p
    return None


HUB = RuntimeHub()
