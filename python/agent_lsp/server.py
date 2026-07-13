"""FastMCP entrypoint — sessions, git worktrees, warm LSP, scout tools."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, cast

from fastmcp import FastMCP

from agent_lsp import paths as paths_mod
from agent_lsp.blast import blast_radius, blast_to_dict
from agent_lsp.paths import ensure_data_dirs, project_bare_path, require_id, workspace_path
from agent_lsp.runtime_hub import HUB

mcp = FastMCP("agent-lsp")

_state: Any = None
_git: Any = None
_docker: Any = None
_docker_error: str | None = None


def get_state() -> Any:
    global _state
    if _state is None:
        from agent_lsp_state import StateStore

        ensure_data_dirs()
        _state = StateStore(str(paths_mod.STATE_DIR / "sessions.db"))
    return _state


def get_git() -> Any:
    global _git
    if _git is None:
        from agent_lsp_git import GitService

        _git = GitService()
    return _git


def get_docker() -> Any | None:
    global _docker, _docker_error
    if _docker is not None:
        return _docker
    if _docker_error is not None:
        return None
    try:
        from agent_lsp_docker import DockerService

        _docker = DockerService()
        return _docker
    except Exception as exc:  # noqa: BLE001
        _docker_error = str(exc)
        return None


def _session_or_err(session_id: str) -> dict[str, Any]:
    row = get_state().get_session(session_id)
    if row is None:
        return {"error": "session_not_found", "session_id": session_id}
    return cast(dict[str, Any], dict(row))


def _active_workspace(session_id: str) -> tuple[dict[str, Any], dict[str, Any]] | dict[str, Any]:
    session = _session_or_err(session_id)
    if "error" in session:
        return session
    wid = session.get("active_workspace_id")
    if not wid:
        return {"error": "no_active_workspace", "session_id": session_id}
    ws = get_state().get_workspace(wid)
    if ws is None or ws.get("status") != "active":
        return {"error": "workspace_unavailable", "workspace_id": wid}
    return session, cast(dict[str, Any], dict(ws))


def _client_for(session_id: str) -> Any | dict[str, Any]:
    rt = HUB.get(session_id)
    if rt is None or rt.client is None:
        return {
            "error": "runtime_not_ready",
            "session_id": session_id,
            "hint": "call ensure_runtime then warm_index",
        }
    return rt.client


# ── sessions ──────────────────────────────────────────────────────────────


@mcp.tool()
def create_session(meta: str = "") -> dict[str, Any]:
    """Create a persistent scout session (holds workspace + containers)."""
    sid = get_state().create_session(meta=meta or None)
    return {"session_id": sid, "index_status": "cold"}


@mcp.tool()
def get_session(session_id: str) -> dict[str, Any]:
    """Read session + bound containers."""
    row = _session_or_err(session_id)
    if "error" in row:
        return row
    containers = [dict(c) for c in get_state().list_containers(session_id)]
    row["containers"] = containers
    live = HUB.get(session_id)
    if live is not None:
        row["live_runtime_mode"] = live.runtime_mode
        row["live_index_status"] = live.index_status
    return row


@mcp.tool()
def list_sessions() -> dict[str, Any]:
    """List all sessions."""
    return {"sessions": [dict(s) for s in get_state().list_sessions()]}


@mcp.tool()
def close_session(session_id: str) -> dict[str, Any]:
    """Stop containers / local LSP and mark session closed."""
    HUB.shutdown(session_id, get_docker())
    get_state().close_session(session_id)
    return {"session_id": session_id, "closed": True}


# ── projects / worktrees ───────────────────────────────────────────────────


@mcp.tool()
def create_project(project_id: str) -> dict[str, Any]:
    """Create an empty bare git project under projects/<id>.git."""
    ensure_data_dirs()
    pid = require_id(project_id, "project_id")
    bare = project_bare_path(pid)
    if bare.exists():
        return {"error": "project_exists", "project_id": pid, "bare": str(bare)}
    path = get_git().init_bare(str(bare))
    return {"project_id": pid, "bare": path}


@mcp.tool()
def import_project(project_id: str, source: str) -> dict[str, Any]:
    """Import real sources into a bare repo.

    `source` is a local git path or a remote URL (https/git/file).
    Uses gix — no git CLI.
    """
    ensure_data_dirs()
    pid = require_id(project_id, "project_id")
    bare = project_bare_path(pid)
    if bare.exists():
        return {"error": "project_exists", "project_id": pid}
    src = Path(source)
    try:
        if src.exists():
            path = get_git().import_local(str(src.resolve()), str(bare))
        else:
            path = get_git().clone_bare(source, str(bare))
    except Exception as exc:  # noqa: BLE001
        return {"error": "import_failed", "detail": str(exc)}
    return {"project_id": pid, "bare": path, "source": source}


@mcp.tool()
def checkout_workspace(
    session_id: str,
    project_id: str,
    ref_name: str = "HEAD",
    workspace_id: str = "",
) -> dict[str, Any]:
    """Add a gix worktree and bind it as the session's active workspace."""
    ensure_data_dirs()
    session = _session_or_err(session_id)
    if "error" in session:
        return session
    pid = require_id(project_id, "project_id")
    bare = project_bare_path(pid)
    if not bare.exists():
        return {"error": "project_not_found", "project_id": pid}
    wid = workspace_id or uuid.uuid4().hex[:12]
    require_id(wid, "workspace_id")
    wt = workspace_path(wid)
    try:
        path = get_git().add_worktree(str(bare), str(wt), ref_name)
    except Exception as exc:  # noqa: BLE001
        return {"error": "checkout_failed", "detail": str(exc)}
    get_state().create_workspace(pid, path, ref_name=ref_name or "HEAD", workspace_id=wid)
    get_state().set_active_workspace(session_id, wid)
    get_state().set_index_status(session_id, "cold")
    return {
        "session_id": session_id,
        "workspace_id": wid,
        "path": path,
        "ref_name": ref_name,
        "project_id": pid,
    }


@mcp.tool()
def commit_workspace(
    session_id: str, message: str, paths: list[str] | None = None
) -> dict[str, Any]:
    """Commit listed paths in the active worktree (gix, no push)."""
    bound = _active_workspace(session_id)
    if isinstance(bound, dict):
        return bound
    _, ws = bound
    try:
        cid = get_git().commit(ws["path"], message, paths or [])
    except Exception as exc:  # noqa: BLE001
        return {"error": "commit_failed", "detail": str(exc)}
    return {"commit": cid, "workspace_id": ws["workspace_id"]}


# ── runtime / index pipeline ───────────────────────────────────────────────


@mcp.tool()
def ensure_runtime(session_id: str, language: str, prefer_container: bool = True) -> dict[str, Any]:
    """Start (or reuse) an LSP runtime held by the session.

    Prefers a long-lived Docker container. Falls back to local subprocess when
    Docker is unavailable — still bound into session state.
    """
    bound = _active_workspace(session_id)
    if isinstance(bound, dict):
        return bound
    _, ws = bound
    workspace = Path(ws["path"])
    docker = get_docker() if prefer_container else None
    try:
        if docker is not None:
            rt = HUB.ensure_container(session_id, workspace, language, docker)
        else:
            rt = HUB.ensure_local(session_id, workspace, language)
    except Exception as exc:  # noqa: BLE001
        # Container failed → local fallback
        if docker is not None:
            try:
                rt = HUB.ensure_local(session_id, workspace, language)
            except Exception as exc2:  # noqa: BLE001
                return {
                    "error": "runtime_failed",
                    "detail": str(exc2),
                    "container_detail": str(exc),
                }
        else:
            return {
                "error": "runtime_failed",
                "detail": str(exc),
                "docker": _docker_error,
            }

    get_state().bind_container(
        session_id,
        rt.container_id or "unknown",
        image=language,
        language=language,
        host_port=rt.host_port,
        runtime_mode=rt.runtime_mode,
    )
    get_state().set_index_status(session_id, "warming")
    return {
        "session_id": session_id,
        "language": language,
        "runtime_mode": rt.runtime_mode,
        "container_id": rt.container_id,
        "host_port": rt.host_port,
        "index_status": "warming",
    }


@mcp.tool()
def warm_index(session_id: str, timeout_seconds: float = 120.0) -> dict[str, Any]:
    """Isolated index + cache warm pipeline for the session runtime."""
    try:
        rt = HUB.warm(session_id, timeout=timeout_seconds)
    except Exception as exc:  # noqa: BLE001
        get_state().set_index_status(session_id, "error")
        return {"error": "warm_failed", "detail": str(exc)}
    get_state().set_index_status(session_id, rt.index_status)
    return {
        "session_id": session_id,
        "index_status": rt.index_status,
        "indexed": True,
        "language": rt.language,
        "runtime_mode": rt.runtime_mode,
        "error": rt.error,
    }


# ── scout tools ────────────────────────────────────────────────────────────


@mcp.tool(name="blast_radius")
def blast_radius_tool(
    session_id: str,
    changed_files: list[str],
    include_transitive: bool = False,
) -> dict[str, Any]:
    """Signature blast-radius analysis on the warm session index."""
    client = _client_for(session_id)
    if isinstance(client, dict):
        return client
    result = blast_radius(
        client, changed_files, include_transitive=include_transitive
    )
    return blast_to_dict(result)


@mcp.tool()
def list_symbols(session_id: str, file_path: str) -> dict[str, Any]:
    """List symbols in a file (documentSymbol)."""
    client = _client_for(session_id)
    if isinstance(client, dict):
        return client
    syms = client.document_symbols(file_path)
    return {
        "file_path": file_path,
        "symbols": [
            {"name": s.name, "kind": s.kind, "line": s.line, "character": s.character}
            for s in syms
        ],
        "indexed": client.is_workspace_loaded(),
    }


@mcp.tool()
def find_references(
    session_id: str,
    file_path: str,
    line: int,
    column: int,
    include_declaration: bool = False,
) -> dict[str, Any]:
    """Find all references to the symbol at position (1-based line/column)."""
    client = _client_for(session_id)
    if isinstance(client, dict):
        return client
    locs = client.references(file_path, line, column, include_declaration)
    return {
        "references": [{"uri": loc.uri, "line": loc.line, "character": loc.character} for loc in locs],
        "indexed": client.is_workspace_loaded(),
    }


@mcp.tool()
def inspect_symbol(
    session_id: str, file_path: str, line: int, column: int
) -> dict[str, Any]:
    """Hover / type info at position."""
    client = _client_for(session_id)
    if isinstance(client, dict):
        return client
    text = client.hover(file_path, line, column)
    return {"hover": text, "indexed": client.is_workspace_loaded()}


@mcp.tool()
def go_to_definition(
    session_id: str, file_path: str, line: int, column: int
) -> dict[str, Any]:
    """Go to definition at position."""
    client = _client_for(session_id)
    if isinstance(client, dict):
        return client
    locs = client.definition(file_path, line, column)
    return {
        "definitions": [
            {"uri": loc.uri, "line": loc.line, "character": loc.character} for loc in locs
        ],
        "indexed": client.is_workspace_loaded(),
    }


@mcp.tool()
def explore_symbol(
    session_id: str, file_path: str, line: int, column: int
) -> dict[str, Any]:
    """Scout composite: hover + definition + references in one call."""
    client = _client_for(session_id)
    if isinstance(client, dict):
        return client
    hover = client.hover(file_path, line, column)
    defs = client.definition(file_path, line, column)
    refs = client.references(file_path, line, column)
    return {
        "hover": hover,
        "definitions": [
            {"uri": d.uri, "line": d.line, "character": d.character} for d in defs
        ],
        "references": [
            {"uri": r.uri, "line": r.line, "character": r.character} for r in refs
        ],
        "indexed": client.is_workspace_loaded(),
    }


def main() -> None:
    ensure_data_dirs()
    mcp.run()


if __name__ == "__main__":
    main()
