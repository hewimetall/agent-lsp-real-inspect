"""Path helpers for projects / workspaces / state."""

from __future__ import annotations

import os
import re
from pathlib import Path

STATE_DIR = Path(os.environ.get("AGENT_LSP_STATE", "state"))
PROJECTS_DIR = Path(os.environ.get("AGENT_LSP_PROJECTS", "projects"))
WORKSPACES_DIR = Path(os.environ.get("AGENT_LSP_WORKSPACES", "workspaces"))
CACHE_DIR = Path(os.environ.get("AGENT_LSP_CACHE", "cache"))

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
    for d in (STATE_DIR, PROJECTS_DIR, WORKSPACES_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
