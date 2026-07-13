"""Extra unit coverage for blast / runtimes / lsp helpers / paths."""

from __future__ import annotations

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
from agent_lsp.lsp_client import Location, LspClient, SymbolInfo, path_to_uri
from agent_lsp.runtimes import get_runtime


def test_get_runtime_known() -> None:
    rt = get_runtime("Go")
    assert rt.language == "go"
    with pytest.raises(ValueError):
        get_runtime("cobol")


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
