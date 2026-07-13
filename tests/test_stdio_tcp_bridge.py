"""Unit tests for infra/docker/lsp/common/stdio_tcp_bridge.py (no Docker)."""

from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

BRIDGE = (
    Path(__file__).resolve().parents[1]
    / "infra"
    / "docker"
    / "lsp"
    / "common"
    / "stdio_tcp_bridge.py"
)


def _load_bridge():
    spec = importlib.util.spec_from_file_location("stdio_tcp_bridge", BRIDGE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bridge_module_exists() -> None:
    assert BRIDGE.is_file()


def test_parse_args_requires_command() -> None:
    mod = _load_bridge()
    with pytest.raises(SystemExit):
        mod._parse_args(["--port", "9"])


def test_parse_args_strips_doubledash() -> None:
    mod = _load_bridge()
    args = mod._parse_args(["--port", "4000", "--", "pyright-langserver", "--stdio"])
    assert args.port == 4000
    assert args.lsp_cmd == ["pyright-langserver", "--stdio"]


def test_bridge_echo_roundtrip() -> None:
    """TCP client ↔ bridge ↔ `cat` stdio."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    proc = subprocess.Popen(
        [sys.executable, str(BRIDGE), "--host", "127.0.0.1", "--port", str(port), "--", "cat"],
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2) as sock:
                    sock.sendall(b"hello-lsp\n")
                    sock.settimeout(2.0)
                    # cat echoes; read until we get our payload (may be partial)
                    buf = b""
                    while b"hello-lsp" not in buf:
                        chunk = sock.recv(64)
                        assert chunk, "connection closed before echo"
                        buf += chunk
                    assert b"hello-lsp" in buf
                    break
            except (ConnectionRefusedError, TimeoutError, OSError):
                time.sleep(0.05)
        else:
            err = proc.stderr.read().decode() if proc.stderr else ""
            raise AssertionError(f"bridge did not accept in time; stderr={err!r}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
