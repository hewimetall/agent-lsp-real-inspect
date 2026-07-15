"""Raise median coverage for deps / env / settings / runtimes / worker install."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent_lsp import env_layout, paths as paths_mod
from agent_lsp.deps import (
    build_apt_only_script,
    build_deps_plan,
    detect_manager,
)
from agent_lsp.lsp_settings import (
    build_lsp_settings,
    configuration_items_response,
    container_path,
)
from agent_lsp.runtimes import (
    normalize_language,
    resolve_image,
    resolve_install_image,
)
from agent_lsp.worker import ScoutWorker


def test_env_layout_cache_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(env_layout, "CACHE_DIR", tmp_path / "cache")
    assert env_layout.node_modules_path(tmp_path) == tmp_path / "node_modules"
    assert env_layout.go_modcache_host("s1").name == "s1"
    assert env_layout.gopls_cache_host("s1").name == "s1"
    assert env_layout.npm_cache_host("s1").name == "s1"
    assert env_layout.pip_cache_host("s1").name == "s1"
    assert env_layout.discover_site_packages(tmp_path) == []
    assert env_layout.read_apt_packages(tmp_path) == []
    env_layout.append_apt_packages(tmp_path, ["", "  ", "curl", "#ignored"])
    # comment lines ignored on read
    apt = env_layout.apt_packages_file(tmp_path)
    apt.write_text("# hi\ncurl\n\n", encoding="utf-8")
    assert env_layout.read_apt_packages(tmp_path) == ["curl"]


def test_runtimes_normalize_and_fallback_versions() -> None:
    assert normalize_language("JS") == "typescript"
    assert normalize_language("ts") == "typescript"
    assert normalize_language("c++") == "cpp"
    assert normalize_language("c") == "cpp"
    assert normalize_language("clangd") == "cpp"
    assert resolve_image("cpp").endswith("agent-lsp-cpp:latest")
    assert resolve_install_image("cpp") == "debian:bookworm"
    assert resolve_image("python", "v3.12").endswith(":3.12")
    assert resolve_image("python", "9.9.9").endswith(":9.9")
    assert resolve_image("go", "1.24").endswith(":1.24")
    assert resolve_image("typescript", "20.11").endswith(":20")
    assert resolve_install_image("python", "9.9") == "python:9.9-bookworm"
    assert resolve_install_image("go", "1.99") == "golang:1.99-bookworm"
    assert resolve_install_image("typescript", "18.0") == "node:18-bookworm"
    assert resolve_install_image("rust") == "rust:1-bookworm"
    assert resolve_image("rust")  # default latest


def test_deps_uv_pnpm_yarn_and_go_get(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.uv]\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    assert detect_manager(tmp_path, "python") == "uv"
    uv = build_deps_plan(tmp_path, "python", manager="uv", packages=["httpx"])
    assert "uv" in uv.script and "httpx" in uv.script
    uv_lock = build_deps_plan(tmp_path, "python", manager="uv", packages=[])
    assert "uv" in uv_lock.script

    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    assert detect_manager(tmp_path, "typescript") == "pnpm"
    pnpm = build_deps_plan(tmp_path, "ts", manager="pnpm", packages=["left-pad"])
    assert "pnpm" in pnpm.script
    yarn = build_deps_plan(tmp_path, "javascript", manager="yarn", packages=[])
    assert "yarn install" in yarn.script
    npm = build_deps_plan(tmp_path, "typescript", manager="npm", packages=[])
    assert "npm install" in npm.script

    go = build_deps_plan(
        tmp_path, "go", packages=["example.com/mod@v1"], apt_packages=["gcc"]
    )
    assert "go get" in go.script and "go mod tidy" in go.script and "gcc" in go.script

    with pytest.raises(ValueError):
        detect_manager(tmp_path, "cobol")
    with pytest.raises(ValueError):
        build_deps_plan(tmp_path, "python", manager="cargo")


def test_lsp_settings_languages_and_config_items(tmp_path: Path) -> None:
    assert "typescript" in build_lsp_settings(tmp_path, "typescript")
    assert "gopls" in build_lsp_settings(tmp_path, "go")
    assert build_lsp_settings(tmp_path, "rust") == {}
    # host path without uri_root
    p = tmp_path / "x.py"
    p.write_text("x=1\n", encoding="utf-8")
    assert container_path(tmp_path, p, None).endswith("x.py")
    # outside root → fallback absolute
    outside = Path("/tmp/not-under-ws")
    assert container_path(tmp_path, outside, Path("/workspace")).startswith("/")
    settings = {"python": {"pythonPath": "/v/bin/python"}, "a": {"b": {"c": 1}}}
    resp = configuration_items_response(
        [{}, {"section": None}, {"section": "python"}, {"section": "a.b.c"}, {"section": "missing.x"}],
        settings,
    )
    assert resp[0] == settings
    assert resp[2]["pythonPath"] == "/v/bin/python"
    assert resp[3] == 1
    assert resp[4] == {}


def test_worker_install_and_apt_with_fake_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_lsp import server
    from agent_lsp.worker import ScoutWorker as SW

    paths_mod.STATE_DIR = tmp_path / "state"
    paths_mod.PROJECTS_DIR = tmp_path / "projects"
    paths_mod.WORKSPACES_DIR = tmp_path / "workspaces"
    paths_mod.CACHE_DIR = tmp_path / "cache"
    for d in (
        paths_mod.STATE_DIR,
        paths_mod.PROJECTS_DIR,
        paths_mod.WORKSPACES_DIR,
        paths_mod.CACHE_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)
    server._state = None
    server._git = None
    server._tasks = None
    server._docker = None
    server._docker_error = None

    class FakeDocker:
        def run(self, *a: Any, **k: Any) -> dict[str, Any]:
            ws = Path(str(k.get("binds", [""])[0]).split(":")[0])
            env_layout.ensure_agent_lsp_dir(ws)
            venv = env_layout.venv_path(ws)
            (venv / "lib" / "python3.12" / "site-packages").mkdir(parents=True, exist_ok=True)
            (venv / "bin").mkdir(parents=True, exist_ok=True)
            (venv / "bin" / "python").write_text("", encoding="utf-8")
            return {"status_code": 0, "logs": "ok", "container_id": "c1"}

    monkeypatch.setattr(server, "get_docker", lambda: FakeDocker())
    monkeypatch.setattr(
        "agent_lsp.worker.wake_worker", lambda tasks: ScoutWorker(tasks)  # type: ignore[arg-type]
    )
    monkeypatch.setattr(server, "wake_worker", lambda tasks: ScoutWorker(tasks))  # type: ignore[arg-type]

    sid = server.create_session()["session_id"]
    server.create_project("covdemo")
    co = server.checkout_workspace(sid, "covdemo")
    wt = Path(co["path"])
    (wt / "app.py").write_text("x=1\n", encoding="utf-8")
    (wt / "requirements.txt").write_text("requests\n", encoding="utf-8")

    q = server.enqueue_install_workspace_deps(
        sid,
        language="python",
        language_version="3.12",
        packages=["requests"],
        apt_packages=["ca-certificates"],
        restart_runtime=False,
    )
    w = SW(server.get_tasks(), poll_seconds=0.01)
    assert w.process_one() is True
    st = server.get_task_status(q["task_id"])
    assert st["status"] == "done"
    art = json.loads(st["artifact"])
    assert art["manager"] == "pip"
    assert art["run"]["mode"] == "container"

    q2 = server.enqueue_install_apt_packages(sid, ["gcc"], language="python")
    assert w.process_one() is True
    assert server.get_task_status(q2["task_id"])["status"] == "done"

    # go + typescript install paths with fake docker
    (wt / "go.mod").write_text("module x\n\ngo 1.23\n", encoding="utf-8")
    q3 = server.enqueue_install_workspace_deps(
        sid, language="go", language_version="1.23", restart_runtime=False
    )
    assert w.process_one() is True
    assert server.get_task_status(q3["task_id"])["status"] == "done"

    (wt / "package.json").write_text("{}", encoding="utf-8")
    q4 = server.enqueue_install_workspace_deps(
        sid, language="typescript", language_version="22", packages=["lodash"], restart_runtime=False
    )
    assert w.process_one() is True
    assert server.get_task_status(q4["task_id"])["status"] == "done"

    # error paths
    assert server.enqueue_install_apt_packages(sid, [])["error"] == "packages_required"
    bad = server.enqueue_install_workspace_deps("missing-session", language="python")
    assert "error" in bad or bad.get("status") == "queued"


def test_cpp_settings_picks_compile_commands(tmp_path: Path) -> None:
    build = tmp_path / "build"
    build.mkdir()
    (build / "compile_commands.json").write_text("[]\n", encoding="utf-8")
    settings = build_lsp_settings(tmp_path, "cpp", uri_root=Path("/workspace"))
    assert settings["clangd"]["compilationDatabasePath"] == "/workspace/build"


def test_typescript_initialization_options_point_at_image_tsserver() -> None:
    from agent_lsp.lsp_settings import build_initialization_options

    opts = build_initialization_options("typescript")
    path = opts["tsserver"]["path"]
    assert path.endswith("typescript/lib/tsserver.js")
    assert opts["tsserver"]["fallbackPath"] == path
    assert build_initialization_options("python") == {}
