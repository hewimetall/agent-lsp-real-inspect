"""Session runtimes — hold containers (or local LSP) and warm clients."""

from __future__ import annotations

import socket
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_lsp.lsp_client import LspClient
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
            self.sessions[rt.session_id] = rt

    def drop(self, session_id: str) -> SessionRuntime | None:
        with self._lock:
            return self.sessions.pop(session_id, None)

    def ensure_local(
        self,
        session_id: str,
        workspace: Path,
        language: str,
    ) -> SessionRuntime:
        existing = self.get(session_id)
        if existing and existing.client and existing.language == language:
            return existing
        spec = get_runtime(language)
        # Prefer TCP listen when the local command template has {port}.
        port = _free_port()
        cmd = [c.replace("{port}", str(port)) for c in spec.local_cmd]
        if any("{port}" in c for c in spec.local_cmd):
            # Start server separately then connect TCP — for gopls-style.
            import subprocess
            import time

            proc = subprocess.Popen(cmd, cwd=str(workspace))
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
            )
        self.put(rt)
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
                    workspace, language, "127.0.0.1", int(published)
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
        self.put(rt)
        return rt

    def warm(self, session_id: str, timeout: float = 120.0) -> SessionRuntime:
        rt = self.get(session_id)
        if rt is None or rt.client is None:
            raise RuntimeError(f"no runtime for session {session_id}")
        rt.index_status = "warming"
        ready = rt.client.wait_until_ready(timeout=timeout)
        # Probe: open a seed file if any source exists.
        seed = _find_seed_file(rt.workspace_path, rt.language)
        if seed is not None:
            try:
                syms = rt.client.document_symbols(seed)
                if syms:
                    rt.client.references(syms[0].file, syms[0].line, syms[0].character)
            except Exception as exc:  # noqa: BLE001
                rt.error = str(exc)
        rt.index_status = "ready" if ready or seed is not None else "ready"
        # Mark loaded for tools even if server never emitted $/progress.
        rt.client._workspace_loaded = True
        self.put(rt)
        return rt

    def shutdown(self, session_id: str, docker: Any | None = None) -> None:
        rt = self.drop(session_id)
        if rt is None:
            return
        if rt.client is not None:
            try:
                rt.client.shutdown()
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
        # pathlib doesn't support brace expand — split manually
        if "{ts,tsx}" in pattern:
            cands = list(root.glob("**/*.ts")) + list(root.glob("**/*.tsx"))
        else:
            cands = list(root.glob(pattern))
        for p in cands:
            if p.is_file() and "node_modules" not in p.parts and "target" not in p.parts:
                return p
    return None


HUB = RuntimeHub()
