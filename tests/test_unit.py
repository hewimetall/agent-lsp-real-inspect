"""Unit tests that do not need native extensions compiled."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_lsp.blast import is_test_file
from agent_lsp.paths import project_bare_path, require_id, workspace_path


def test_require_id_ok() -> None:
    assert require_id("demo-1") == "demo-1"


def test_require_id_bad() -> None:
    with pytest.raises(ValueError):
        require_id("../etc")


def test_paths() -> None:
    assert project_bare_path("demo").name == "demo.git"
    assert workspace_path("ws1").name == "ws1"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("foo_test.go", True),
        ("foo.test.ts", True),
        ("test_foo.py", True),
        ("foo.go", False),
        ("pkg/bar.py", False),
    ],
)
def test_is_test_file(path: str, expected: bool) -> None:
    assert is_test_file(path) is expected


def test_blast_to_dict_empty(tmp_path: Path) -> None:
    from agent_lsp.blast import BlastResult, blast_to_dict

    d = blast_to_dict(BlastResult(symbols=[], changed_files=["a.go"], indexed=False))
    assert d["changed_files"] == ["a.go"]
    assert d["symbols"] == []
