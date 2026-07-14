"""Workspace-local env paths for deps visible to LSP (venv / node_modules / go cache)."""

from __future__ import annotations

from pathlib import Path

from agent_lsp.paths import CACHE_DIR

AGENT_LSP_DIR = ".agent-lsp"
VENV_DIRNAME = "venv"
APT_PACKAGES_FILE = "apt-packages.txt"


def agent_lsp_dir(workspace: Path) -> Path:
    return workspace / AGENT_LSP_DIR


def venv_path(workspace: Path) -> Path:
    return agent_lsp_dir(workspace) / VENV_DIRNAME


def apt_packages_file(workspace: Path) -> Path:
    return agent_lsp_dir(workspace) / APT_PACKAGES_FILE


def node_modules_path(workspace: Path) -> Path:
    return workspace / "node_modules"


def go_modcache_host(session_id: str) -> Path:
    return CACHE_DIR / "gomod" / session_id


def gopls_cache_host(session_id: str) -> Path:
    return CACHE_DIR / "gopls" / session_id


def npm_cache_host(session_id: str) -> Path:
    return CACHE_DIR / "npm" / session_id


def pip_cache_host(session_id: str) -> Path:
    return CACHE_DIR / "pip" / session_id


def ensure_agent_lsp_dir(workspace: Path) -> Path:
    d = agent_lsp_dir(workspace)
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_apt_packages(workspace: Path) -> list[str]:
    path = apt_packages_file(workspace)
    if not path.is_file():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if item and not item.startswith("#"):
            out.append(item)
    return out


def append_apt_packages(workspace: Path, packages: list[str]) -> list[str]:
    ensure_agent_lsp_dir(workspace)
    existing = read_apt_packages(workspace)
    merged = list(existing)
    for pkg in packages:
        name = pkg.strip()
        if name and name not in merged:
            merged.append(name)
    apt_packages_file(workspace).write_text(
        "\n".join(merged) + ("\n" if merged else ""), encoding="utf-8"
    )
    return merged


def discover_site_packages(workspace: Path) -> list[Path]:
    """Locate site-packages under the workspace venv (any pythonX.Y)."""
    root = venv_path(workspace) / "lib"
    if not root.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(root.iterdir()):
        sp = child / "site-packages"
        if sp.is_dir():
            found.append(sp)
    return found
