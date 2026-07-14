"""Unit tests for deps plans, runtime image resolution, and LSP settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_lsp import env_layout
from agent_lsp.deps import build_apt_only_script, build_deps_plan, detect_manager
from agent_lsp.lsp_settings import build_lsp_settings, configuration_items_response
from agent_lsp.runtimes import resolve_image, resolve_install_image


def test_resolve_image_version_and_override() -> None:
    assert resolve_image("python", "3.11").endswith(":3.11")
    assert resolve_image("python", image="custom:tag") == "custom:tag"
    assert resolve_install_image("python", "3.14") == "python:3.14-bookworm"
    assert resolve_install_image("go", "1.23") == "golang:1.23-bookworm"
    assert resolve_install_image("typescript", "22") == "node:22-bookworm"


def test_detect_manager_and_python_plan(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    assert detect_manager(tmp_path, "python") == "pip"
    plan = build_deps_plan(
        tmp_path,
        "python",
        language_version="3.11",
        packages=["dramatiq"],
        apt_packages=["build-essential"],
    )
    assert plan.manager == "pip"
    assert plan.install_image == "python:3.11-bookworm"
    assert "python3 -m venv" in plan.script
    assert "build-essential" in plan.script
    assert "dramatiq" in plan.script


def test_node_and_go_plans(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    npm = build_deps_plan(tmp_path, "typescript", packages=["lodash"])
    assert npm.manager == "npm"
    assert "npm install" in npm.script
    (tmp_path / "go.mod").write_text("module example\n\ngo 1.23\n", encoding="utf-8")
    go = build_deps_plan(tmp_path, "go", language_version="1.23")
    assert go.manager == "go"
    assert "go mod download" in go.script


def test_apt_persist_and_script(tmp_path: Path) -> None:
    merged = env_layout.append_apt_packages(tmp_path, ["libpq-dev", "gcc"])
    assert merged == ["libpq-dev", "gcc"]
    again = env_layout.append_apt_packages(tmp_path, ["gcc", "make"])
    assert again == ["libpq-dev", "gcc", "make"]
    script = build_apt_only_script(["curl"])
    assert "apt-get install" in script
    with pytest.raises(ValueError):
        build_apt_only_script([])


def test_lsp_settings_site_packages(tmp_path: Path) -> None:
    sp = tmp_path / ".agent-lsp" / "venv" / "lib" / "python3.11" / "site-packages"
    sp.mkdir(parents=True)
    (tmp_path / ".agent-lsp" / "venv" / "bin").mkdir(parents=True)
    py = tmp_path / ".agent-lsp" / "venv" / "bin" / "python"
    py.write_text("", encoding="utf-8")
    settings = build_lsp_settings(tmp_path, "python", uri_root=Path("/workspace"))
    assert settings["python"]["pythonPath"].startswith("/workspace/.agent-lsp/venv")
    assert any("site-packages" in p for p in settings["python.analysis"]["extraPaths"])
    items = [{"section": "python"}, {"section": "python.analysis"}]
    resp = configuration_items_response(items, settings)
    assert "pythonPath" in resp[0]
    assert "extraPaths" in resp[1]
