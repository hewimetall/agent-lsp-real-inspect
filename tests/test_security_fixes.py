"""Tests for path containment and bugbot/security fixes."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_lsp.blast import _looks_exported, uri_to_path
from agent_lsp.lsp_client import SymbolInfo
from agent_lsp.paths import resolve_under_root
from agent_lsp.runtime_hub import RuntimeHub, SessionRuntime


def test_resolve_under_root_ok(tmp_path: Path) -> None:
    f = tmp_path / "src" / "a.py"
    f.parent.mkdir()
    f.write_text("x=1\n", encoding="utf-8")
    assert resolve_under_root(tmp_path, "src/a.py") == f.resolve()
    assert resolve_under_root(tmp_path, f) == f.resolve()


def test_resolve_under_root_rejects_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        resolve_under_root(tmp_path, "../outside")
    outside = tmp_path.parent / "secret"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_under_root(tmp_path, str(outside))


def test_looks_exported_filters_private() -> None:
    assert _looks_exported(SymbolInfo("Foo", 12, 1, 1, "a.go"), "go")
    assert not _looks_exported(SymbolInfo("bar", 12, 1, 1, "a.go"), "go")
    assert not _looks_exported(SymbolInfo("_priv", 12, 1, 1, "a.py"), "python")
    assert _looks_exported(SymbolInfo("pub", 12, 1, 1, "a.py"), "python")
    assert not _looks_exported(SymbolInfo("x", 1, 1, 1, "a.py"), "python")  # kind not exported


def test_uri_to_path_decodes() -> None:
    assert " " in uri_to_path("file:///tmp/my%20file.py") or "%20" not in uri_to_path(
        "file:///tmp/my%20file.py"
    )


def test_warm_error_when_no_seed(tmp_path: Path) -> None:
    hub = RuntimeHub()
    client = type(
        "C",
        (),
        {
            "wait_until_ready": lambda self, timeout=120.0: False,
            "document_symbols": lambda self, p: [],
            "_workspace_loaded": False,
        },
    )()
    hub.put(
        SessionRuntime(
            session_id="s",
            workspace_path=tmp_path,
            language="python",
            runtime_mode="local",
            client=client,  # type: ignore[arg-type]
        )
    )
    rt = hub.warm("s", timeout=0.05)
    assert rt.index_status == "error"
