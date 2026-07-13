#!/usr/bin/env python3
"""TCP ↔ stdio bridge for language servers that only speak LSP over stdio.

agent-lsp connects to containers on TCP :3737 (see agent_lsp.runtimes /
runtime_hub.ensure_container). gopls can listen natively; pyright,
typescript-language-server, and rust-analyzer need this bridge.

Usage:
  stdio_tcp_bridge.py [--host 0.0.0.0] [--port 3737] -- <lsp> [args...]
"""

from __future__ import annotations

import argparse
import selectors
import signal
import socket
import subprocess
import sys
from typing import BinaryIO


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=3737)
    parser.add_argument(
        "lsp_cmd",
        nargs=argparse.REMAINDER,
        help="Language server command after `--`",
    )
    args = parser.parse_args(argv)
    cmd = list(args.lsp_cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        parser.error("missing language server command after `--`")
    args.lsp_cmd = cmd
    return args


def _pump(sock: socket.socket, proc: subprocess.Popen[bytes]) -> int:
    """Bidirectional byte copy until either side closes. Returns process exit code."""
    assert proc.stdin is not None and proc.stdout is not None
    stdin: BinaryIO = proc.stdin
    stdout: BinaryIO = proc.stdout
    sel = selectors.DefaultSelector()
    sel.register(sock, selectors.EVENT_READ, "sock")
    sel.register(stdout, selectors.EVENT_READ, "stdout")

    try:
        while True:
            if proc.poll() is not None:
                return int(proc.returncode or 0)
            for key, _ in sel.select(timeout=1.0):
                if key.data == "sock":
                    data = sock.recv(65536)
                    if not data:
                        return int(proc.poll() or 0)
                    stdin.write(data)
                    stdin.flush()
                else:
                    data = stdout.read1(65536) if hasattr(stdout, "read1") else stdout.read(65536)
                    if not data:
                        return int(proc.poll() or 0)
                    sock.sendall(data)
    finally:
        sel.close()


def _serve_once(conn: socket.socket, cmd: list[str]) -> int:
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        bufsize=0,
    )
    try:
        return _pump(conn, proc)
    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:  # noqa: BLE001
            pass


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    stop = False

    def _handle_signal(signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.host, args.port))
        server.listen(1)
        print(
            f"stdio-tcp-bridge listening on {args.host}:{args.port} → {args.lsp_cmd}",
            file=sys.stderr,
            flush=True,
        )
        while not stop:
            server.settimeout(1.0)
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            with conn:
                print(f"client connected from {addr}", file=sys.stderr, flush=True)
                code = _serve_once(conn, args.lsp_cmd)
                print(f"client session ended code={code}", file=sys.stderr, flush=True)
                # Session-held containers stay up for reconnects; loop accept again.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
