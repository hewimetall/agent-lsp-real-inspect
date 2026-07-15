"""Tests for mirrors.toml catalog + mirror: source resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_lsp import mirrors as mirrors_mod


def test_load_catalog_from_repo_toml() -> None:
    cat = mirrors_mod.load_catalog(Path("infra/mirrors/mirrors.toml"))
    assert "ceph" in cat.entries
    assert "minio" in cat.entries
    assert "cpython" in cat.entries
    assert "postgres" in cat.entries
    assert cat.get("ceph").url.endswith("ceph/ceph.git")
    assert cat.get("cngp").url == ""
    assert not cat.get("cngp").syncable
    assert "python-build" in cat.get("cryptography").tags


def test_parse_mirror_source() -> None:
    assert mirrors_mod.parse_mirror_source("mirror:ceph") == "ceph"
    assert mirrors_mod.parse_mirror_source("mirror://Ceph") == "Ceph"
    assert mirrors_mod.parse_mirror_source("https://github.com/x/y") is None
    assert mirrors_mod.parse_mirror_source("/tmp/foo") is None


def test_resolve_mirror_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "mirrors.toml"
    toml.write_text(
        """
[[mirror]]
id = "demo"
url = "https://example.com/demo.git"
ref = "main"
depth = 1
kind = "shallow"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_LSP_MIRRORS_TOML", str(toml))
    monkeypatch.setenv("AGENT_LSP_MIRRORS", str(tmp_path / "mirrors"))
    with pytest.raises(FileNotFoundError, match="not synced"):
        mirrors_mod.resolve_source("mirror:demo")


def test_resolve_mirror_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "mirrors.toml"
    toml.write_text(
        """
[[mirror]]
id = "demo"
url = "https://example.com/demo.git"
""",
        encoding="utf-8",
    )
    root = tmp_path / "mirrors"
    bare = root / "demo.git"
    bare.mkdir(parents=True)
    (bare / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_LSP_MIRRORS_TOML", str(toml))
    monkeypatch.setenv("AGENT_LSP_MIRRORS", str(root))
    resolved = mirrors_mod.resolve_source("mirror:demo")
    assert Path(resolved) == bare.resolve()


def test_resolve_empty_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "mirrors.toml"
    toml.write_text(
        """
[[mirror]]
id = "cngp"
url = ""
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_LSP_MIRRORS_TOML", str(toml))
    monkeypatch.setenv("AGENT_LSP_MIRRORS", str(tmp_path / "mirrors"))
    with pytest.raises(FileNotFoundError, match="empty url"):
        mirrors_mod.resolve_source("mirror:cngp")


def test_resolve_passthrough_url() -> None:
    assert mirrors_mod.resolve_source("https://github.com/a/b.git") == (
        "https://github.com/a/b.git"
    )


def test_import_project_mirror_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_lsp._tasks import TaskStore
    from agent_lsp.worker import ScoutWorker
    from agent_lsp import paths as paths_mod
    import json

    paths_mod.PROJECTS_DIR = tmp_path / "projects"
    paths_mod.PROJECTS_DIR.mkdir()
    toml = tmp_path / "m.toml"
    toml.write_text(
        '[[mirror]]\nid = "demo"\nurl = "https://example.com/x.git"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENT_LSP_MIRRORS_TOML", str(toml))
    monkeypatch.setenv("AGENT_LSP_MIRRORS", str(tmp_path / "mirrors"))

    store = TaskStore(str(tmp_path / "t.db"))
    tid = store.submit(
        "",
        str(tmp_path),
        "import_project",
        json.dumps({"project_id": "demo", "source": "mirror:demo"}),
    )
    w = ScoutWorker(store)
    assert w.process_one() is True
    row = store.get(tid)
    assert row["status"] == "error"
    assert "not synced" in (row.get("error") or "")
