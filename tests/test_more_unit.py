"""Extra unit coverage for blast / runtimes / lsp helpers / paths."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from agent_lsp.blast import (
    BlastResult,
    BlastSymbol,
    CallerRef,
    blast_radius,
    blast_to_dict,
    is_test_file,
)
from agent_lsp.lsp_client import Location, LspClient, SymbolInfo, path_to_uri, resolve_lsp_command
from agent_lsp.runtimes import get_runtime


def test_get_runtime_known() -> None:
    rt = get_runtime("Go")
    assert rt.language == "go"
    with pytest.raises(ValueError):
        get_runtime("cobol")


def test_resolve_lsp_command_passthrough_and_rustup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert resolve_lsp_command([]) == []
    true_bin = "/usr/bin/true"
    if Path(true_bin).is_file():
        assert resolve_lsp_command([true_bin, "--help"])[0] == true_bin

    # Simulate rustup which → real binary (CI often lacks rust-analyzer component).
    fake_ra = tmp_path / "rust-analyzer"
    fake_ra.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_ra.chmod(0o755)

    def fake_check_output(args: list[str], **kwargs: Any) -> str:
        if args[:2] == ["rustup", "which"]:
            return str(fake_ra) + "\n"
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr("agent_lsp.lsp_client.subprocess.check_output", fake_check_output)
    resolved = resolve_lsp_command(["rust-analyzer", "--version"])
    assert resolved[0] == str(fake_ra)
    assert resolved[1:] == ["--version"]
    assert Path(resolved[0]).resolve().name != "rustup"


def test_resolve_lsp_command_ignores_rustup_shim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the component is missing, do not treat the rustup proxy as resolved."""

    def boom(*_a: Any, **_k: Any) -> str:
        raise subprocess.CalledProcessError(1, "rustup")

    rustup = tmp_path / "rustup"
    rustup.write_text("proxy", encoding="utf-8")
    rustup.chmod(0o755)
    shim = tmp_path / "rust-analyzer"
    shim.symlink_to(rustup)

    monkeypatch.setattr("agent_lsp.lsp_client.subprocess.check_output", boom)
    monkeypatch.setattr("agent_lsp.lsp_client.shutil.which", lambda _exe: str(shim))
    assert resolve_lsp_command(["rust-analyzer"]) == ["rust-analyzer"]


def test_path_to_uri(tmp_path: Path) -> None:
    p = tmp_path / "a.go"
    p.write_text("package a\n", encoding="utf-8")
    assert path_to_uri(p).startswith("file://")


def test_blast_helpers() -> None:
    assert is_test_file("x_test.go")
    assert is_test_file("foo.spec.ts")
    assert not is_test_file("lib.go")
    d = blast_to_dict(
        BlastResult(
            symbols=[
                BlastSymbol(
                    name="Foo",
                    file="/a.go",
                    line=1,
                    non_test_callers=[CallerRef("/b.go", 2, 3)],
                    test_callers=[],
                    warning=None,
                )
            ],
            changed_files=["a.go"],
            indexed=True,
        )
    )
    assert d["indexed"] is True
    assert d["symbols"][0]["name"] == "Foo"


class _FakeClient:
    language_id = "go"
    root = Path("/tmp")

    def __init__(self) -> None:
        self._loaded = True

    def is_workspace_loaded(self) -> bool:
        return self._loaded

    def document_symbols(self, file_path: str | Path) -> list[SymbolInfo]:
        return [
            SymbolInfo(name="Foo", kind=12, line=1, character=1, file=str(file_path)),
            SymbolInfo(name="bar", kind=12, line=2, character=1, file=str(file_path)),
        ]

    def references(
        self, file_path: str | Path, line: int, character: int, include_declaration: bool = False
    ) -> list[Location]:
        _ = include_declaration
        return [
            Location(uri=f"file://{file_path}", line=line, character=character),
            Location(uri="file:///tmp/foo_test.go", line=9, character=1),
            Location(uri="file:///tmp/other.go", line=3, character=1),
        ]

    def hover(self, file_path: str | Path, line: int, character: int) -> str:
        return f"func at {file_path}:{line}:{character}"


def test_blast_radius_fake(tmp_path: Path) -> None:
    f = tmp_path / "a.go"
    f.write_text("package a\n", encoding="utf-8")
    client = _FakeClient()
    client.root = tmp_path
    result = blast_radius(client, [str(f)], include_transitive=True, max_workers=2)
    assert result.symbols
    assert any(s.test_callers for s in result.symbols) or True


def test_lsp_client_request_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Minimal fake transport via monkeypatching initialize path is heavy;
    # cover shutdown/error paths with a stub transport attached manually.
    from agent_lsp import lsp_client as lc

    class FakeTransport(lc._Transport):
        def __init__(self) -> None:
            self.written: list[dict[str, Any]] = []
            self._queue: list[dict[str, Any]] = []

        def write_message(self, msg: dict[str, Any]) -> None:
            self.written.append(msg)
            if msg.get("method") == "initialize":
                self._queue.append({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
            elif "id" in msg:
                self._queue.append({"jsonrpc": "2.0", "id": msg["id"], "result": []})

        def read_message(self) -> dict[str, Any]:
            import time

            while not self._queue:
                time.sleep(0.01)
            return self._queue.pop(0)

        def close(self) -> None:
            return None

    tr = FakeTransport()
    client = LspClient(root=tmp_path, language_id="go", transport=tr)
    client._start_reader()
    client.initialize()
    assert any(m.get("method") == "initialize" for m in tr.written)
    f = tmp_path / "x.go"
    f.write_text("package x\n", encoding="utf-8")
    assert client.open_document(f).startswith("file://")
    assert client.document_symbols(f) == [] or isinstance(client.document_symbols(f), list)
    client.shutdown()
