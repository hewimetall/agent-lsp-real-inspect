"""Detect package managers and build install / apt bootstrap scripts."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent_lsp import env_layout

Manager = Literal["pip", "uv", "npm", "pnpm", "yarn", "go", "auto"]


@dataclass(frozen=True)
class DepsPlan:
    language: str
    manager: str
    language_version: str
    packages: tuple[str, ...]
    apt_packages: tuple[str, ...]
    extra_args: tuple[str, ...]
    script: str
    install_image: str


def detect_manager(workspace: Path, language: str, manager: str = "auto") -> str:
    key = (manager or "auto").lower().strip()
    if key != "auto":
        return key
    lang = language.lower().strip()
    if lang == "python":
        if (workspace / "uv.lock").is_file() or (
            (workspace / "pyproject.toml").is_file()
            and "tool.uv" in (workspace / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
        ):
            return "uv"
        return "pip"
    if lang in {"typescript", "javascript", "js", "ts"}:
        if (workspace / "pnpm-lock.yaml").is_file():
            return "pnpm"
        if (workspace / "yarn.lock").is_file():
            return "yarn"
        return "npm"
    if lang == "go":
        return "go"
    if lang == "rust":
        return "cargo"
    raise ValueError(f"cannot auto-detect package manager for language={language!r}")


def _apt_prefix(packages: list[str]) -> str:
    if not packages:
        return "true"
    quoted = " ".join(shlex.quote(p) for p in packages)
    return (
        "export DEBIAN_FRONTEND=noninteractive; "
        "apt-get update -y && "
        f"apt-get install -y --no-install-recommends {quoted}"
    )


def _python_script(
    manager: str,
    packages: list[str],
    apt_packages: list[str],
    extra_args: list[str],
) -> str:
    venv = f"{env_layout.AGENT_LSP_DIR}/{env_layout.VENV_DIRNAME}"
    extra = " ".join(shlex.quote(a) for a in extra_args)
    pkg_args = " ".join(shlex.quote(p) for p in packages)
    lines = [
        "set -euo pipefail",
        _apt_prefix(apt_packages),
        f'mkdir -p "{env_layout.AGENT_LSP_DIR}"',
        f'if [ ! -x "{venv}/bin/python" ]; then python3 -m venv "{venv}"; fi',
        f'"{venv}/bin/python" -m pip install -U pip setuptools wheel',
    ]
    if manager == "uv":
        lines.append(f'"{venv}/bin/python" -m pip install -U uv')
        if (packages):
            lines.append(f'"{venv}/bin/uv" pip install {pkg_args} {extra}'.rstrip())
        else:
            lines.append(
                f'if [ -f pyproject.toml ] || [ -f requirements.txt ]; then '
                f'"{venv}/bin/uv" pip install -r requirements.txt {extra} 2>/dev/null '
                f'|| "{venv}/bin/uv" sync {extra}; fi'.rstrip()
            )
    else:
        if packages:
            lines.append(f'"{venv}/bin/pip" install {pkg_args} {extra}'.rstrip())
        else:
            lines.append(
                "if [ -f requirements.txt ]; then "
                f'"{venv}/bin/pip" install -r requirements.txt {extra}; '
                "elif [ -f pyproject.toml ]; then "
                f'"{venv}/bin/pip" install .{extra and " " + extra}; '
                "fi"
            )
    return "\n".join(lines)


def _node_script(
    manager: str,
    packages: list[str],
    apt_packages: list[str],
    extra_args: list[str],
) -> str:
    extra = " ".join(shlex.quote(a) for a in extra_args)
    pkg_args = " ".join(shlex.quote(p) for p in packages)
    if manager == "pnpm":
        install = f"pnpm install {extra}".rstrip()
        add = f"pnpm add {pkg_args} {extra}".rstrip() if packages else ""
    elif manager == "yarn":
        install = f"yarn install {extra}".rstrip()
        add = f"yarn add {pkg_args} {extra}".rstrip() if packages else ""
    else:
        install = f"npm install {extra}".rstrip()
        add = f"npm install {pkg_args} {extra}".rstrip() if packages else ""
    lines = [
        "set -euo pipefail",
        _apt_prefix(apt_packages),
        install if not packages else add or install,
    ]
    if packages and manager == "npm":
        # `npm install pkg` already installs; still ensure lock-based install when no pkgs
        pass
    elif not packages:
        pass
    return "\n".join(lines)


def _go_script(
    packages: list[str],
    apt_packages: list[str],
    extra_args: list[str],
) -> str:
    extra = " ".join(shlex.quote(a) for a in extra_args)
    lines = [
        "set -euo pipefail",
        _apt_prefix(apt_packages),
        f"go mod download {extra}".rstrip(),
    ]
    for pkg in packages:
        lines.append(f"go get {shlex.quote(pkg)}")
    if packages:
        lines.append("go mod tidy")
    return "\n".join(lines)


def build_deps_plan(
    workspace: Path,
    language: str,
    *,
    language_version: str = "",
    manager: str = "auto",
    packages: list[str] | None = None,
    apt_packages: list[str] | None = None,
    extra_args: list[str] | None = None,
    install_image: str = "",
) -> DepsPlan:
    from agent_lsp.runtimes import resolve_install_image

    lang = language.lower().strip()
    if lang in {"js", "ts", "javascript"}:
        lang = "typescript"
    mgr = detect_manager(workspace, lang, manager)
    pkgs = [p.strip() for p in (packages or []) if p and p.strip()]
    apt = [p.strip() for p in (apt_packages or []) if p and p.strip()]
    # Merge persisted apt list (from install_apt_packages).
    for p in env_layout.read_apt_packages(workspace):
        if p not in apt:
            apt.append(p)
    extra = list(extra_args or [])
    if mgr in {"pip", "uv"}:
        script = _python_script(mgr, pkgs, apt, extra)
    elif mgr in {"npm", "pnpm", "yarn"}:
        script = _node_script(mgr, pkgs, apt, extra)
    elif mgr == "go":
        script = _go_script(pkgs, apt, extra)
    else:
        raise ValueError(f"unsupported package manager: {mgr}")
    image = install_image or resolve_install_image(lang, language_version)
    return DepsPlan(
        language=lang,
        manager=mgr,
        language_version=language_version or "",
        packages=tuple(pkgs),
        apt_packages=tuple(apt),
        extra_args=tuple(extra),
        script=script,
        install_image=image,
    )


def build_apt_only_script(packages: list[str]) -> str:
    pkgs = [p.strip() for p in packages if p and p.strip()]
    if not pkgs:
        raise ValueError("packages must be non-empty")
    return "\n".join(["set -euo pipefail", _apt_prefix(pkgs)])
