"""Build LSP workspace/configuration payloads so deps resolve (site-packages, etc.)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_lsp import env_layout
from agent_lsp.runtimes import normalize_language


def container_path(host_root: Path, host_path: Path, uri_root: Path | None) -> str:
    if uri_root is None:
        return str(host_path.resolve())
    try:
        rel = host_path.resolve().relative_to(host_root.resolve())
        return str(uri_root / rel)
    except ValueError:
        return str(host_path.resolve())


def build_lsp_settings(
    workspace: Path,
    language: str,
    *,
    uri_root: Path | None = None,
) -> dict[str, Any]:
    """Settings returned for ``workspace/configuration`` (and didChangeConfiguration)."""
    lang = normalize_language(language)
    if lang == "python":
        venv = env_layout.venv_path(workspace)
        python_bin = venv / "bin" / "python"
        settings: dict[str, Any] = {
            "python": {
                "venvPath": container_path(workspace, env_layout.agent_lsp_dir(workspace), uri_root),
                "venv": env_layout.VENV_DIRNAME,
            },
            "python.analysis": {
                "diagnosticMode": "workspace",
                "extraPaths": [
                    container_path(workspace, sp, uri_root)
                    for sp in env_layout.discover_site_packages(workspace)
                ],
            },
        }
        if python_bin.exists():
            settings["python"]["pythonPath"] = container_path(workspace, python_bin, uri_root)
            settings["python"]["defaultInterpreterPath"] = settings["python"]["pythonPath"]
        return settings
    if lang == "typescript":
        return {
            # Cap heap for small VPS hosts (3–4 GiB); 4096 OOMs initialize.
            "typescript": {"tsserver": {"maxTsServerMemory": 768}},
            "javascript": {"suggest": {"enabled": True}},
        }
    if lang == "go":
        return {"gopls": {"directoryFilters": ["-**/node_modules"]}}
    if lang == "cpp":
        # clangd finds compile_commands.json by walking parents of opened files.
        # Prefer an explicit compilation database when present in the worktree.
        for name in ("compile_commands.json", "build/compile_commands.json"):
            db = workspace / name
            if db.is_file():
                return {
                    "clangd": {
                        "compilationDatabasePath": container_path(
                            workspace, db.parent, uri_root
                        )
                    }
                }
        return {"clangd": {}}
    return {}


# Global TypeScript from the LSP image (pinned typescript@5.x — has tsserver.js).
_CONTAINER_TSSERVER = "/usr/local/lib/node_modules/typescript/lib/tsserver.js"


def build_initialization_options(language: str) -> dict[str, Any]:
    """LSP ``initialize.initializationOptions`` for the language server."""
    lang = normalize_language(language)
    if lang == "typescript":
        # Prefer workspace typescript; fall back to the image-global install so
        # repos without a local `typescript` dependency still initialize.
        return {
            "tsserver": {
                "path": _CONTAINER_TSSERVER,
                "fallbackPath": _CONTAINER_TSSERVER,
            }
        }
    return {}


def configuration_items_response(
    items: list[dict[str, Any]], settings: dict[str, Any]
) -> list[Any]:
    """Answer workspace/configuration requests item-by-item."""
    out: list[Any] = []
    for item in items:
        section = (item or {}).get("section")
        if not section:
            out.append(settings)
            continue
        # Nested section lookup: "python.analysis" → settings["python.analysis"] or drill-down.
        if section in settings:
            out.append(settings[section])
            continue
        cur: Any = settings
        ok = True
        for part in str(section).split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        out.append(cur if ok else {})
    return out
