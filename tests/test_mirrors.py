"""Tests for mirrors.toml catalog + mirror: source resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_lsp import mirrors as mirrors_mod
from agent_lsp import paths as paths_mod


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
    assert cat.list()
    assert cat.toml_path.name == "mirrors.toml"


def test_parse_mirror_source() -> None:
    assert mirrors_mod.parse_mirror_source("mirror:ceph") == "ceph"
    assert mirrors_mod.parse_mirror_source("mirror://Ceph") == "Ceph"
    assert mirrors_mod.parse_mirror_source("https://github.com/x/y") is None
    assert mirrors_mod.parse_mirror_source("/tmp/foo") is None
    assert mirrors_mod.parse_mirror_source("") is None
    with pytest.raises(ValueError, match="empty mirror id"):
        mirrors_mod.parse_mirror_source("mirror:")
    with pytest.raises(ValueError, match="empty mirror id"):
        mirrors_mod.parse_mirror_source("mirror://")
    with pytest.raises(ValueError, match="empty mirror id"):
        mirrors_mod.parse_mirror_source("mirror:///")


def test_resolve_empty_mirror_prefix_fail_closed() -> None:
    with pytest.raises(ValueError, match="empty mirror id"):
        mirrors_mod.resolve_source("mirror:")
    with pytest.raises(ValueError, match="empty mirror id"):
        mirrors_mod.resolve_source("mirror://")


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


def test_resolve_rejects_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toml = tmp_path / "mirrors.toml"
    toml.write_text(
        '[[mirror]]\nid = "demo"\nurl = "https://example.com/x.git"\n',
        encoding="utf-8",
    )
    root = tmp_path / "mirrors"
    root.mkdir()
    outside = tmp_path / "outside.git"
    outside.mkdir()
    (outside / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    bare = root / "demo.git"
    bare.symlink_to(outside)
    monkeypatch.setenv("AGENT_LSP_MIRRORS_TOML", str(toml))
    monkeypatch.setenv("AGENT_LSP_MIRRORS", str(root))
    with pytest.raises(ValueError, match="escapes mirrors root"):
        mirrors_mod.resolve_source("mirror:demo")


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


def test_load_catalog_rejects_table_and_bad_id(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text("[mirrors]\nceph = {url='x'}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected \\[\\[mirror\\]\\]"):
        mirrors_mod.load_catalog(bad)
    bad2 = tmp_path / "bad2.toml"
    bad2.write_text('[[mirror]]\nid = "../x"\nurl = "https://e/x.git"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid mirror_id"):
        mirrors_mod.load_catalog(bad2)


def test_mirrors_dir_sibling_of_projects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_LSP_MIRRORS", raising=False)
    monkeypatch.setattr(paths_mod, "PROJECTS_DIR", Path("/var/lib/agent-lsp/projects"))
    assert paths_mod.mirrors_dir() == Path("/var/lib/agent-lsp/mirrors")
    assert mirrors_mod.mirrors_root() == Path("/var/lib/agent-lsp/mirrors")


def test_mirrors_toml_path_prefer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_LSP_MIRRORS_TOML", raising=False)
    prefer = tmp_path / "infra" / "mirrors" / "mirrors.toml"
    prefer.parent.mkdir(parents=True)
    prefer.write_text('[[mirror]]\nid = "x"\nurl = "https://e/x.git"\n', encoding="utf-8")
    assert mirrors_mod.mirrors_toml_path(prefer=prefer) == prefer


def test_import_project_mirror_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_lsp._tasks import TaskStore
    from agent_lsp.worker import ScoutWorker

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


def test_import_project_empty_mirror_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_lsp._tasks import TaskStore
    from agent_lsp.worker import ScoutWorker

    paths_mod.PROJECTS_DIR = tmp_path / "projects"
    paths_mod.PROJECTS_DIR.mkdir()
    store = TaskStore(str(tmp_path / "t2.db"))
    tid = store.submit(
        "",
        str(tmp_path),
        "import_project",
        json.dumps({"project_id": "x", "source": "mirror:"}),
    )
    w = ScoutWorker(store)
    assert w.process_one() is True
    row = store.get(tid)
    assert row["status"] == "error"
    assert "empty mirror id" in (row.get("error") or "")


def test_ensure_data_dirs_uses_mirrors_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_LSP_MIRRORS", str(tmp_path / "m"))
    monkeypatch.setattr(paths_mod, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(paths_mod, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(paths_mod, "WORKSPACES_DIR", tmp_path / "ws")
    monkeypatch.setattr(paths_mod, "CACHE_DIR", tmp_path / "cache")
    paths_mod.ensure_data_dirs()
    assert (tmp_path / "m").is_dir()
