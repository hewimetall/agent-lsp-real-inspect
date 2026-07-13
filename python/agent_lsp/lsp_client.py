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
        if resolved and Path(resolved).is_file():
            return [resolved, *cmd[1:]]
    except (OSError, subprocess.CalledProcessError):
        pass
    which = shutil.which(exe)
    if which:
        real = Path(which).resolve()
        if real.name != "rustup":
            return [which, *cmd[1:]]
        # Last resort: pin rustup toolchain via env at spawn time (caller may set it).
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
        self.sock.settimeout(timeout)
        self._rfile = self.sock.makefile("rb")
        self._lock = threading.Lock()

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
    _next_id: int = 1
    _pending: dict[int, dict[str, Any] | None] = field(default_factory=dict)
    _reader: threading.Thread | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _workspace_loaded: bool = False
    _open_docs: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _cond: threading.Condition = field(default_factory=threading.Condition)

    @classmethod
    def connect_tcp(cls, root: Path, language_id: str, host: str, port: int) -> LspClient:
        transport = TcpTransport(host, port)
        client = cls(root=root, language_id=language_id, transport=transport)
        client._start_reader()
        client.initialize()
        return client

    @classmethod
    def spawn_local(cls, root: Path, language_id: str, cmd: list[str]) -> LspClient:
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
        client = cls(root=root, language_id=language_id, transport=transport)
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
            elif msg.get("method") == "window/workDoneProgress/create":
                # auto-ack
                rid = msg.get("id")
                if rid is not None:
                    self.transport.write_message({"jsonrpc": "2.0", "id": rid, "result": None})

    def request(self, method: str, params: dict[str, Any] | None = None, timeout: float = 60.0) -> Any:
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
        root_uri = path_to_uri(self.root)
        result = self.request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": root_uri,
                "rootPath": str(self.root),
                "capabilities": {
                    "workspace": {"workspaceFolders": True},
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
                "workspaceFolders": [{"uri": root_uri, "name": self.root.name}],
            },
            timeout=120.0,
        )
        self.notify("initialized", {})
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
        uri = path_to_uri(path)
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
            locs.append(
                Location(
                    uri=item.get("uri", ""),
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
                    uri=target,
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
