"""Minimal LSP JSON-RPC client (stdio or TCP)."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote


def resolve_lsp_command(cmd: list[str]) -> list[str]:
    """Resolve argv[0] to a real executable, bypassing rustup cwd toolchain shims.

    Spawning ``rust-analyzer`` with ``cwd=<project>`` makes the rustup proxy pick the
    project's (or rustup default) toolchain, which may not have the rust-analyzer
    component. Resolve against ``AGENT_LSP_RUSTUP_TOOLCHAIN`` / ``stable`` instead.

    Never returns a rustup proxy shim as a "resolved" path — callers would still hit
    the wrong toolchain. If no real binary is found, the original argv is returned.
    """
    if not cmd:
        return cmd
    exe = cmd[0]
    path = Path(exe)
    if path.is_file() and os.access(path, os.X_OK):
        real = path.resolve()
        if real.name != "rustup":
            return cmd
    name = path.name
    toolchain = os.environ.get("AGENT_LSP_RUSTUP_TOOLCHAIN", "stable")
    try:
        resolved = subprocess.check_output(
            ["rustup", "which", "--toolchain", toolchain, name],
            text=True,
            cwd="/",
            stderr=subprocess.DEVNULL,
        ).strip()
        if resolved and Path(resolved).is_file() and Path(resolved).resolve().name != "rustup":
            return [resolved, *cmd[1:]]
    except (OSError, subprocess.CalledProcessError):
        pass
    which = shutil.which(exe)
    if which and Path(which).resolve().name != "rustup":
        return [which, *cmd[1:]]
    return cmd


def path_to_uri(path: str | Path) -> str:
    p = Path(path).resolve()
    return "file://" + quote(p.as_posix())


@dataclass
class Position:
    line: int  # 0-based
    character: int  # 0-based


@dataclass
class Location:
    uri: str
    line: int  # 1-based for agent output
    character: int  # 1-based


@dataclass
class SymbolInfo:
    name: str
    kind: int
    line: int  # 1-based
    character: int  # 1-based
    file: str


class LspError(RuntimeError):
    pass


class _Transport:
    def read_message(self) -> dict[str, Any]:
        raise NotImplementedError

    def write_message(self, msg: dict[str, Any]) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class StdioTransport(_Transport):
    def __init__(self, proc: subprocess.Popen[bytes]) -> None:
        self.proc = proc
        assert proc.stdin and proc.stdout
        self.stdin = proc.stdin
        self.stdout = proc.stdout
        self._lock = threading.Lock()

    def write_message(self, msg: dict[str, Any]) -> None:
        body = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        with self._lock:
            self.stdin.write(header + body)
            self.stdin.flush()

    def read_message(self) -> dict[str, Any]:
        headers: dict[str, str] = {}
        while True:
            line = self.stdout.readline()
            if not line:
                raise LspError("LSP stdout closed")
            if line in (b"\r\n", b"\n"):
                break
            key, _, val = line.decode("ascii", errors="replace").partition(":")
            headers[key.strip().lower()] = val.strip()
        length = int(headers.get("content-length", "0"))
        body = self.stdout.read(length)
        return json.loads(body.decode("utf-8"))

    def close(self) -> None:
        with self._lock:
            try:
                self.stdin.close()
            except Exception:
                pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


class TcpTransport(_Transport):
    def __init__(self, host: str, port: int, timeout: float = 30.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        # Connect uses `timeout`, but the reader must block indefinitely: pyright
        # (and others) go quiet after initialize, and a short socket timeout kills
        # the reader thread so later warm_index requests hang until request timeout.
        self.sock.settimeout(None)
        self._rfile = self.sock.makefile("rb")
        self._lock = threading.Lock()

    def is_alive(self) -> bool:
        """Best-effort: False when the peer closed or the socket is in error.

        Docker can still report the container as Running while clangd/the bridge
        has dropped the TCP session — that is the Broken-pipe production failure.
        """
        try:
            err = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if err:
                return False
            # Non-blocking peek: b"" means orderly shutdown by peer.
            self.sock.settimeout(0)
            try:
                chunk = self.sock.recv(1, socket.MSG_PEEK)
            except BlockingIOError:
                return True
            except ConnectionError:
                return False
            finally:
                self.sock.settimeout(None)
            return chunk != b""
        except OSError:
            return False

    def write_message(self, msg: dict[str, Any]) -> None:
        body = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        with self._lock:
            self.sock.sendall(header + body)

    def read_message(self) -> dict[str, Any]:
        headers: dict[str, str] = {}
        while True:
            line = self._rfile.readline()
            if not line:
                raise LspError("LSP TCP closed")
            if line in (b"\r\n", b"\n"):
                break
            key, _, val = line.decode("ascii", errors="replace").partition(":")
            headers[key.strip().lower()] = val.strip()
        length = int(headers.get("content-length", "0"))
        body = self._rfile.read(length)
        return json.loads(body.decode("utf-8"))

    def close(self) -> None:
        try:
            self._rfile.close()
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


@dataclass
class LspClient:
    root: Path
    language_id: str
    transport: _Transport
    # When the LSP runs in a container, host `root` is bind-mounted at `uri_root`
    # (e.g. /workspace). All LSP URIs must use the container path; file IO stays on host.
    uri_root: Path | None = None
    # workspace/configuration + didChangeConfiguration payload (venv, extraPaths, …).
    settings: dict[str, Any] = field(default_factory=dict)
    # LSP initialize.initializationOptions (e.g. tsserver.path for typescript).
    initialization_options: dict[str, Any] = field(default_factory=dict)
    _next_id: int = 1
    _pending: dict[int, dict[str, Any] | None] = field(default_factory=dict)
    _reader: threading.Thread | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _workspace_loaded: bool = False
    _open_docs: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _cond: threading.Condition = field(default_factory=threading.Condition)

    @classmethod
    def connect_tcp(
        cls,
        root: Path,
        language_id: str,
        host: str,
        port: int,
        *,
        uri_root: Path | None = None,
        settings: dict[str, Any] | None = None,
        initialization_options: dict[str, Any] | None = None,
    ) -> LspClient:
        transport = TcpTransport(host, port)
        client = cls(
            root=root,
            language_id=language_id,
            transport=transport,
            uri_root=uri_root,
            settings=dict(settings or {}),
            initialization_options=dict(initialization_options or {}),
        )
        client._start_reader()
        client.initialize()
        return client

    @classmethod
    def spawn_local(
        cls,
        root: Path,
        language_id: str,
        cmd: list[str],
        *,
        settings: dict[str, Any] | None = None,
        initialization_options: dict[str, Any] | None = None,
    ) -> LspClient:
        resolved = resolve_lsp_command(cmd)
        # Discard stderr so a chatty language server cannot fill the PIPE and deadlock.
        # Keep a DEVNULL handle (not None) so the child does not inherit the parent tty.
        proc = subprocess.Popen(
            resolved,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(root),
        )
        transport = StdioTransport(proc)
        client = cls(
            root=root,
            language_id=language_id,
            transport=transport,
            settings=dict(settings or {}),
            initialization_options=dict(initialization_options or {}),
        )
        client._start_reader()
        client.initialize()
        return client

    def _start_reader(self) -> None:
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self.transport.read_message()
            except Exception:
                break
            if "id" in msg and ("result" in msg or "error" in msg):
                with self._cond:
                    self._pending[int(msg["id"])] = msg
                    self._cond.notify_all()
            elif msg.get("method") == "$/progress":
                value = (msg.get("params") or {}).get("value") or {}
                if value.get("kind") == "end":
                    self._workspace_loaded = True
            elif msg.get("method") in {
                "window/workDoneProgress/create",
                "client/registerCapability",
                "client/unregisterCapability",
                "workspace/configuration",
                "workspace/workspaceFolders",
            }:
                # Auto-ack common server→client requests so the LS does not stall.
                rid = msg.get("id")
                if rid is not None:
                    result: Any = None
                    method = msg.get("method")
                    if method == "workspace/configuration":
                        from agent_lsp.lsp_settings import configuration_items_response

                        items = ((msg.get("params") or {}).get("items")) or []
                        result = configuration_items_response(items, self.settings)
                    elif method == "workspace/workspaceFolders":
                        lsp_root = self.uri_root if self.uri_root is not None else self.root
                        result = [
                            {
                                "uri": path_to_uri(lsp_root),
                                "name": lsp_root.name or self.root.name,
                            }
                        ]
                    self.transport.write_message(
                        {"jsonrpc": "2.0", "id": rid, "result": result}
                    )

    def _to_uri(self, path: Path) -> str:
        """Host path → LSP file URI (container uri_root when set)."""
        resolved = path.resolve()
        if self.uri_root is not None:
            try:
                rel = resolved.relative_to(self.root.resolve())
                return path_to_uri(self.uri_root / rel)
            except ValueError:
                pass
        return path_to_uri(resolved)

    def _from_uri(self, uri: str) -> str:
        """LSP file URI → host filesystem path."""
        from urllib.parse import unquote, urlparse

        if uri.startswith("file://"):
            remote = unquote(urlparse(uri).path)
        else:
            remote = unquote(uri)
        if self.uri_root is not None:
            try:
                rel = Path(remote).relative_to(self.uri_root)
                return str((self.root / rel).resolve())
            except ValueError:
                pass
        return remote

    def apply_settings(self, settings: dict[str, Any]) -> None:
        self.settings = dict(settings)
        self.notify("workspace/didChangeConfiguration", {"settings": self.settings})

    def transport_alive(self) -> bool:
        """Whether the underlying stdio/TCP transport still looks usable."""
        t = self.transport
        if isinstance(t, TcpTransport):
            return t.is_alive()
        if isinstance(t, StdioTransport):
            return t.proc.poll() is None
        return True

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 60.0) -> Any:
        # rust-analyzer (and others) may reply -32801 ContentModified while the
        # index is still settling; retry a few times before surfacing the error.
        attempts = 4
        last_err: Exception | None = None
        for attempt in range(attempts):
            try:
                return self._request_once(method, params, timeout=timeout)
            except LspError as exc:
                last_err = exc
                msg = str(exc)
                if "-32801" in msg or "content modified" in msg.lower():
                    time.sleep(0.15 * (attempt + 1))
                    continue
                raise
        assert last_err is not None
        raise last_err

    def _request_once(
        self, method: str, params: dict[str, Any] | None = None, timeout: float = 60.0
    ) -> Any:
        with self._lock:
            rid = self._next_id
            self._next_id += 1
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        with self._cond:
            self._pending[rid] = None
        self.transport.write_message(msg)
        deadline = time.time() + timeout
        with self._cond:
            while self._pending.get(rid) is None:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise LspError(f"timeout waiting for {method}")
                self._cond.wait(timeout=remaining)
            resp = self._pending.pop(rid)
        assert resp is not None
        if "error" in resp:
            raise LspError(f"{method}: {resp['error']}")
        return resp.get("result")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.transport.write_message(msg)

    def initialize(self) -> None:
        lsp_root = self.uri_root if self.uri_root is not None else self.root
        root_uri = path_to_uri(lsp_root)
        # TCP-attached language servers (containers / remote) must not receive a
        # host processId: pyright watches that PID and exits when it is absent
        # from the server's PID namespace. Local stdio keeps os.getpid().
        process_id = None if isinstance(self.transport, TcpTransport) else os.getpid()
        params: dict[str, Any] = {
            "processId": process_id,
            "rootUri": root_uri,
            "rootPath": str(lsp_root),
            "capabilities": {
                "workspace": {
                    "workspaceFolders": True,
                    "configuration": True,
                },
                "textDocument": {
                    "synchronization": {"didOpen": True, "didClose": True},
                    "hover": {"contentFormat": ["plaintext", "markdown"]},
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                    "references": {},
                    "definition": {},
                    "implementation": {},
                    "callHierarchy": {},
                    "publishDiagnostics": {},
                },
                "window": {"workDoneProgress": True},
            },
            "workspaceFolders": [
                {"uri": root_uri, "name": lsp_root.name or self.root.name}
            ],
        }
        if self.initialization_options:
            params["initializationOptions"] = self.initialization_options
        result = self.request(
            "initialize",
            params,
            timeout=120.0,
        )
        self.notify("initialized", {})
        if self.settings:
            self.notify("workspace/didChangeConfiguration", {"settings": self.settings})
        _ = result

    def is_workspace_loaded(self) -> bool:
        return self._workspace_loaded

    def wait_until_ready(self, timeout: float = 120.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._workspace_loaded:
                return True
            time.sleep(0.2)
        return self._workspace_loaded

    def open_document(self, file_path: str | Path) -> str:
        from agent_lsp.paths import resolve_under_root

        path = resolve_under_root(self.root, file_path)
        uri = self._to_uri(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        version = self._open_docs.get(uri, 0) + 1
        self._open_docs[uri] = version
        if version == 1:
            self.notify(
                "textDocument/didOpen",
                {
                    "textDocument": {
                        "uri": uri,
                        "languageId": self.language_id,
                        "version": version,
                        "text": text,
                    }
                },
            )
        else:
            self.notify(
                "textDocument/didChange",
                {
                    "textDocument": {"uri": uri, "version": version},
                    "contentChanges": [{"text": text}],
                },
            )
        return uri

    def document_symbols(self, file_path: str | Path) -> list[SymbolInfo]:
        from agent_lsp.paths import resolve_under_root

        uri = self.open_document(file_path)
        result = self.request(
            "textDocument/documentSymbol",
            {"textDocument": {"uri": uri}},
        )
        out: list[SymbolInfo] = []
        path = str(resolve_under_root(self.root, file_path))

        def walk(nodes: list[Any], prefix: str = "") -> None:
            for n in nodes or []:
                name = n.get("name") or ""
                kind = int(n.get("kind") or 0)
                # DocumentSymbol (hierarchical) vs SymbolInformation (flat).
                if "location" in n and "range" not in n and "selectionRange" not in n:
                    loc = n["location"]
                    rng = (loc.get("range") or {}).get("start") or {}
                    out.append(
                        SymbolInfo(
                            name=name,
                            kind=kind,
                            line=int(rng.get("line", 0)) + 1,
                            character=int(rng.get("character", 0)) + 1,
                            file=path,
                        )
                    )
                    continue
                full = f"{prefix}{name}" if not prefix else f"{prefix}.{name}"
                sel = n.get("selectionRange") or n.get("range") or {}
                start = sel.get("start") or {}
                out.append(
                    SymbolInfo(
                        name=full,
                        kind=kind,
                        line=int(start.get("line", 0)) + 1,
                        character=int(start.get("character", 0)) + 1,
                        file=path,
                    )
                )
                if "children" in n:
                    walk(n.get("children") or [], full)

        if isinstance(result, list):
            walk(result)
        return out

    def references(
        self, file_path: str | Path, line: int, character: int, include_declaration: bool = False
    ) -> list[Location]:
        """line/character are 1-based."""
        uri = self.open_document(file_path)
        result = self.request(
            "textDocument/references",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line - 1, "character": character - 1},
                "context": {"includeDeclaration": include_declaration},
            },
        )
        locs: list[Location] = []
        for item in result or []:
            rng = (item.get("range") or {}).get("start") or {}
            raw_uri = item.get("uri", "")
            locs.append(
                Location(
                    uri=path_to_uri(self._from_uri(raw_uri)) if raw_uri else "",
                    line=int(rng.get("line", 0)) + 1,
                    character=int(rng.get("character", 0)) + 1,
                )
            )
        return locs

    def hover(self, file_path: str | Path, line: int, character: int) -> str:
        uri = self.open_document(file_path)
        result = self.request(
            "textDocument/hover",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line - 1, "character": character - 1},
            },
        )
        if not result:
            return ""
        contents = result.get("contents")
        if isinstance(contents, str):
            return contents
        if isinstance(contents, dict):
            return str(contents.get("value") or "")
        if isinstance(contents, list):
            parts: list[str] = []
            for c in contents:
                if isinstance(c, str):
                    parts.append(c)
                elif isinstance(c, dict):
                    parts.append(str(c.get("value") or ""))
            return "\n".join(parts)
        return str(contents)

    def definition(self, file_path: str | Path, line: int, character: int) -> list[Location]:
        uri = self.open_document(file_path)
        result = self.request(
            "textDocument/definition",
            {
                "textDocument": {"uri": uri},
                "position": {"line": line - 1, "character": character - 1},
            },
        )
        items = result if isinstance(result, list) else ([result] if result else [])
        locs: list[Location] = []
        for item in items:
            target = item.get("targetUri") or item.get("uri") or ""
            rng = (
                (item.get("targetSelectionRange") or item.get("targetRange") or item.get("range") or {})
                .get("start")
                or {}
            )
            locs.append(
                Location(
                    uri=path_to_uri(self._from_uri(target)) if target else "",
                    line=int(rng.get("line", 0)) + 1,
                    character=int(rng.get("character", 0)) + 1,
                )
            )
        return locs

    def shutdown(self) -> None:
        try:
            self.request("shutdown", None, timeout=10.0)
            self.notify("exit", None)
        except Exception:
            pass
        self._stop.set()
        self.transport.close()
