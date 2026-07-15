"""Path helpers for projects / workspaces / state + containment."""

from __future__ import annotations

import os
import re
from pathlib import Path

STATE_DIR = Path(os.environ.get("AGENT_LSP_STATE", "state"))
PROJECTS_DIR = Path(os.environ.get("AGENT_LSP_PROJECTS", "projects"))
WORKSPACES_DIR = Path(os.environ.get("AGENT_LSP_WORKSPACES", "workspaces"))
CACHE_DIR = Path(os.environ.get("AGENT_LSP_CACHE", "cache"))
MIRRORS_DIR = Path(os.environ.get("AGENT_LSP_MIRRORS", "mirrors"))

_SAFE_ID = re.compile(r"^[a-zA-Z0-9._-]{1,128}$")


def require_id(value: str, kind: str = "id") -> str:
    if not _SAFE_ID.match(value):
        raise ValueError(f"invalid {kind}: {value!r}")
    return value


def project_bare_path(project_id: str) -> Path:
    return PROJECTS_DIR / f"{require_id(project_id, 'project_id')}.git"


def workspace_path(workspace_id: str) -> Path:
    return WORKSPACES_DIR / require_id(workspace_id, "workspace_id")


def ensure_data_dirs() -> None:
    for d in (STATE_DIR, PROJECTS_DIR, WORKSPACES_DIR, CACHE_DIR, MIRRORS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def resolve_under_root(root: Path, file_path: str | Path) -> Path:
    """Resolve ``file_path`` and require it stays under ``root``.

    Rejects absolute paths outside the root and ``..`` escapes.
    """
    root_resolved = root.resolve()
    candidate = Path(file_path)
    if not candidate.is_absolute():
        candidate = root_resolved / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(
            f"path escapes workspace root: {file_path!r} (root={root_resolved})"
        ) from exc
    return resolved
