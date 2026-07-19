"""FastMCP entrypoint — TaskStore + sessions/worktrees + scout tools."""

from __future__ import annotations

import json
import uuid
from contextlib import suppress
from datetime import timedelta
from typing import Any, cast

from fastmcp import Context, FastMCP
from fastmcp.dependencies import Progress
from fastmcp.server.tasks import TaskConfig

from agent_lsp import paths as paths_mod
from agent_lsp.blast import blast_radius, blast_to_dict
from agent_lsp.client_compat import prefers_progress_over_tasks
from agent_lsp.client_middleware import ClientCompatMiddleware
from agent_lsp.paths import ensure_data_dirs, project_bare_path, require_id, workspace_path
from agent_lsp.runtime_hub import HUB
from agent_lsp.task_bridge import await_sqlite_task
from agent_lsp.worker import wake_worker

mcp = FastMCP("agent-lsp")
mcp.add_middleware(ClientCompatMiddleware())

# Important scout prompts → MCP prompts/list (not an HTTP /prompt route).
from agent_lsp.prompts import register_prompts  # noqa: E402

register_prompts(mcp)

_state: Any = None
_git: Any = None
_docker: Any = None
_docker_error: str | None = None
_tasks: Any = None

# Long scout ops: optional Tasks (SEP-1686) so Cursor can use ordinary tools/call
# + notifications/progress. Task-capable clients (vmcp) may still pass task=True.
# ADR-0001 amended for Cursor compat — see docs/guide/tasks.md.
_SCOUT_TASK = TaskConfig(mode="optional", poll_interval=timedelta(seconds=1))


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


def get_tasks() -> Any:
    global _tasks
    if _tasks is None:
        from agent_lsp._tasks import TaskStore

        ensure_data_dirs()
        _tasks = TaskStore(str(paths_mod.STATE_DIR / "tasks.db"))
    return _tasks


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
    except Exception as exc:
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


def _runtime_stale_payload(session_id: str, *, hint: str, detail: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {
        "error": "runtime_stale",
        "session_id": session_id,
        "hint": hint,
    }
    if detail:
        out["detail"] = detail
    return out


def _is_stale_transport_error(exc: BaseException) -> bool:
    if isinstance(exc, (BrokenPipeError, ConnectionError, ConnectionResetError)):
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in {
        32,  # EPIPE
        104,  # ECONNRESET
    }:
        return True
    from agent_lsp.lsp_client import LspError

    if isinstance(exc, LspError):
        msg = str(exc).lower()
        return any(
            token in msg
            for token in (
                "broken pipe",
                "tcp closed",
                "stdout closed",
                "connection reset",
                "connection refused",
            )
        )
    return False


def _client_for(session_id: str) -> Any | dict[str, Any]:
    rt = HUB.get(session_id)
    if rt is None:
        return {
            "error": "runtime_not_ready",
            "session_id": session_id,
            "hint": "call ensure_runtime then warm_index",
        }
    # After mark_runtime_stale, client is cleared but needs_recycle stays True —
    # prefer runtime_stale so callers know to re-ensure, not cold-start onboard.
    if rt.needs_recycle or rt.index_status == "stale":
        return _runtime_stale_payload(
            session_id,
            hint="runtime needs recycle — call ensure_runtime then warm_index",
            detail=rt.error or "",
        )
    if rt.client is None:
        return {
            "error": "runtime_not_ready",
            "session_id": session_id,
            "hint": "call ensure_runtime then warm_index",
        }
    if (
        rt.runtime_mode == "container"
        and rt.container_id
    ):
        docker = get_docker()
        if docker is not None and hasattr(docker, "is_running"):
            try:
                if not docker.is_running(rt.container_id):
                    HUB.mark_runtime_stale(
                        session_id,
                        reason="docker reports container not running",
                    )
                    return _runtime_stale_payload(
                        session_id,
                        hint="container died — call ensure_runtime then warm_index",
                    )
            except Exception:
                pass
    # Container Up ≠ LSP socket alive (prod Broken pipe).
    if not HUB._client_transport_alive(rt):
        HUB.mark_runtime_stale(
            session_id,
            reason="LSP TCP transport dead (Broken pipe / peer closed)",
        )
        return _runtime_stale_payload(
            session_id,
            hint="LSP connection lost — call ensure_runtime then warm_index",
        )
    return rt.client


def _with_lsp_client(
    session_id: str, fn: Any
) -> Any:
    """Run ``fn(client)``; on Broken pipe mark runtime stale instead of 500."""
    client = _client_for(session_id)
    if isinstance(client, dict):
        return client
    try:
        return fn(client)
    except Exception as exc:
        if not _is_stale_transport_error(exc):
            raise
        HUB.mark_runtime_stale(session_id, reason=f"LSP transport failed: {exc}")
        return _runtime_stale_payload(
            session_id,
            hint="LSP connection lost — call ensure_runtime then warm_index",
            detail=str(exc),
        )


def _task_row(row: object) -> dict[str, Any]:
    return cast(dict[str, Any], dict(row))  # type: ignore[arg-type]


class _CtxProgress:
    """Bridge SQLite status lines onto Context.report_progress (Cursor path)."""

    def __init__(self, ctx: Context, total: float = 3.0) -> None:
        self._ctx = ctx
        self._total = total
        self._current = 0.0

    async def set_message(self, message: str | None) -> None:
        if not message:
            return
        with suppress(Exception):
            await self._ctx.report_progress(self._current, self._total, message)

    async def set_total(self, total: float) -> None:
        self._total = float(total)

    async def increment(self, amount: float = 1.0) -> None:
        self._current = min(self._total, self._current + float(amount))
        with suppress(Exception):
            await self._ctx.report_progress(self._current, self._total, None)


def _progress_reporter(
    progress: Progress, ctx: Context | None
) -> tuple[Any | None, _CtxProgress | None]:
    """Prefer FastMCP Progress impl; fall back to Context for Cursor-style clients."""
    if getattr(progress, "_impl", None) is not None:
        return progress, None
    if ctx is not None and prefers_progress_over_tasks(ctx):
        return None, _CtxProgress(ctx)
    if ctx is not None:
        return None, _CtxProgress(ctx)
    return None, None


async def _wait_queued_task(
    tid: str, progress: Progress, ctx: Context | None = None
) -> dict[str, Any]:
    reporter, ctx_prog = _progress_reporter(progress, ctx)
    sink: Any | None = reporter if reporter is not None else ctx_prog
    if reporter is not None:
        with suppress(Exception):
            await reporter.set_total(3)
            await reporter.set_message(f"task_id={tid} status=queued")
    elif ctx_prog is not None:
        with suppress(Exception):
            await ctx_prog.set_total(3)
            await ctx_prog.set_message(f"task_id={tid} status=queued")
    try:
        row = await await_sqlite_task(get_tasks(), tid, sink)
        if reporter is not None:
            with suppress(Exception):
                await reporter.increment(3)
        elif ctx_prog is not None:
            with suppress(Exception):
                await ctx_prog.increment(3)
        # Prefer structured artifact JSON when present.
        art = row.get("artifact")
        if row.get("status") == "done" and art:
            with suppress(json.JSONDecodeError, TypeError):
                parsed = json.loads(str(art))
                if isinstance(parsed, dict):
                    parsed["task_id"] = tid
                    parsed["status"] = "done"
                    return parsed
        return row
    except TimeoutError as exc:
        # Only mark error if the worker has not already finished.
        from agent_lsp.task_bridge import TERMINAL

        current = get_tasks().get(tid)
        if current is not None and current.get("status") not in TERMINAL:
            with suppress(Exception):
                get_tasks().update(tid, status="error", error=str(exc))
        return {"error": "wait_timeout", "task_id": tid, "detail": str(exc)}


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


def enqueue_import_project(project_id: str, source: str) -> dict[str, Any]:
    """Submit import_project into SQLite TaskStore and wake ScoutWorker."""
    ensure_data_dirs()
    try:
        pid = require_id(project_id, "project_id")
    except ValueError as exc:
        return {"error": "invalid_id", "detail": str(exc)}
    bare = project_bare_path(pid)
    if bare.exists():
        return {"error": "project_exists", "project_id": pid}
    payload = json.dumps({"project_id": pid, "source": source})
    tid = get_tasks().submit("", str(bare.parent), "import_project", payload)
    wake_worker(get_tasks())
    return {"task_id": tid, "status": "queued", "target": "import_project"}


@mcp.tool(task=_SCOUT_TASK)
async def import_project(
    project_id: str,
    source: str,
    ctx: Context | None = None,
    progress: Progress = Progress(),
) -> dict[str, Any]:
    """Import real sources into a bare repo (gix).

    ``source`` may be a git URL, a local path, or ``mirror:<id>`` /
    ``mirror://<id>`` from ``infra/mirrors/mirrors.toml`` (must be synced
    first via ``scripts/mirror-sync.py`` — never auto-fetched).

    Prefer MCP ``task=True`` when the client supports Tasks; Cursor uses
    ordinary ``tools/call`` + ``notifications/progress``.
    """
    queued = enqueue_import_project(project_id, source)
    if "error" in queued:
        return queued
    return await _wait_queued_task(str(queued["task_id"]), progress, ctx)


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
    except Exception as exc:
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
    except Exception as exc:
        return {"error": "commit_failed", "detail": str(exc)}
    return {"commit": cid, "workspace_id": ws["workspace_id"]}


# ── runtime / index pipeline (task-required) ───────────────────────────────


def enqueue_ensure_runtime(
    session_id: str,
    language: str,
    prefer_container: bool = True,
    language_version: str = "",
    image: str = "",
) -> dict[str, Any]:
    bound = _active_workspace(session_id)
    if isinstance(bound, dict):
        return bound
    _, ws = bound
    payload = json.dumps(
        {
            "language": language,
            "prefer_container": prefer_container,
            "language_version": language_version,
            "image": image,
        }
    )
    tid = get_tasks().submit(session_id, ws["path"], "ensure_runtime", payload)
    wake_worker(get_tasks())
    return {
        "task_id": tid,
        "status": "queued",
        "target": "ensure_runtime",
        "workspace": ws["path"],
    }


@mcp.tool(task=_SCOUT_TASK)
async def ensure_runtime(
    session_id: str,
    language: str,
    prefer_container: bool = True,
    language_version: str = "",
    image: str = "",
    ctx: Context | None = None,
    progress: Progress = Progress(),
) -> dict[str, Any]:
    """Start LSP runtime held by the session (**Docker container**).

    ``language_version`` pins the interpreter/toolchain (e.g. python ``3.11``,
    go ``1.23``, node ``22``). ``image`` overrides the resolved LSP image tag.
    Local host LSPs are disabled unless ``AGENT_LSP_ALLOW_LOCAL=1`` and
    ``prefer_container=false`` (tests/dev only).
    """
    queued = enqueue_ensure_runtime(
        session_id,
        language,
        prefer_container,
        language_version=language_version,
        image=image,
    )
    if "error" in queued:
        return queued
    return await _wait_queued_task(str(queued["task_id"]), progress, ctx)


def enqueue_install_workspace_deps(
    session_id: str,
    language: str = "",
    language_version: str = "",
    manager: str = "auto",
    packages: list[str] | None = None,
    apt_packages: list[str] | None = None,
    extra_args: list[str] | None = None,
    restart_runtime: bool = True,
    install_image: str = "",
) -> dict[str, Any]:
    bound = _active_workspace(session_id)
    if isinstance(bound, dict):
        return bound
    _, ws = bound
    payload = json.dumps(
        {
            "language": language,
            "language_version": language_version,
            "manager": manager,
            "packages": packages or [],
            "apt_packages": apt_packages or [],
            "extra_args": extra_args or [],
            "restart_runtime": restart_runtime,
            "install_image": install_image,
        }
    )
    tid = get_tasks().submit(session_id, ws["path"], "install_workspace_deps", payload)
    wake_worker(get_tasks())
    return {
        "task_id": tid,
        "status": "queued",
        "target": "install_workspace_deps",
        "workspace": ws["path"],
    }


@mcp.tool(task=_SCOUT_TASK)
async def install_workspace_deps(
    session_id: str,
    language: str = "",
    language_version: str = "",
    manager: str = "auto",
    packages: list[str] | None = None,
    apt_packages: list[str] | None = None,
    extra_args: list[str] | None = None,
    restart_runtime: bool = True,
    install_image: str = "",
    ctx: Context | None = None,
    progress: Progress = Progress(),
) -> dict[str, Any]:
    """Install project / ad-hoc deps into the active workspace (venv, node_modules, go mod).

    For Python, creates ``.agent-lsp/venv`` so blast/LSP resolve into site-packages.
    Optional ``apt_packages`` run in the same throwaway install container (no allowlist).
    Cursor: sync call + progress; task-capable clients may pass task=True.
    """
    queued = enqueue_install_workspace_deps(
        session_id,
        language=language,
        language_version=language_version,
        manager=manager,
        packages=packages,
        apt_packages=apt_packages,
        extra_args=extra_args,
        restart_runtime=restart_runtime,
        install_image=install_image,
    )
    if "error" in queued:
        return queued
    return await _wait_queued_task(str(queued["task_id"]), progress, ctx)


def enqueue_install_apt_packages(
    session_id: str,
    packages: list[str],
    language: str = "",
    language_version: str = "",
    install_image: str = "",
) -> dict[str, Any]:
    bound = _active_workspace(session_id)
    if isinstance(bound, dict):
        return bound
    _, ws = bound
    if not packages:
        return {"error": "packages_required", "session_id": session_id}
    payload = json.dumps(
        {
            "packages": packages,
            "language": language,
            "language_version": language_version,
            "install_image": install_image,
        }
    )
    tid = get_tasks().submit(session_id, ws["path"], "install_apt_packages", payload)
    wake_worker(get_tasks())
    return {
        "task_id": tid,
        "status": "queued",
        "target": "install_apt_packages",
        "workspace": ws["path"],
    }


@mcp.tool(task=_SCOUT_TASK)
async def install_apt_packages(
    session_id: str,
    packages: list[str],
    language: str = "",
    language_version: str = "",
    install_image: str = "",
    ctx: Context | None = None,
    progress: Progress = Progress(),
) -> dict[str, Any]:
    """Record + attempt apt packages with no allowlist validation (build bootstrap).

    Names are shell-quoted only. The list is persisted under
    ``.agent-lsp/apt-packages.txt`` and reapplied on ``install_workspace_deps``.
    Cursor: sync call + progress; task-capable clients may pass task=True.
    """
    queued = enqueue_install_apt_packages(
        session_id,
        packages,
        language=language,
        language_version=language_version,
        install_image=install_image,
    )
    if "error" in queued:
        return queued
    return await _wait_queued_task(str(queued["task_id"]), progress, ctx)


def enqueue_warm_index(session_id: str, timeout_seconds: float = 120.0) -> dict[str, Any]:
    bound = _active_workspace(session_id)
    if isinstance(bound, dict):
        return bound
    _, ws = bound
    if HUB.get(session_id) is None:
        return {
            "error": "runtime_not_ready",
            "session_id": session_id,
            "hint": "call ensure_runtime first",
        }
    payload = json.dumps({"timeout_seconds": timeout_seconds})
    tid = get_tasks().submit(session_id, ws["path"], "warm_index", payload)
    get_state().set_index_status(session_id, "warming")
    wake_worker(get_tasks())
    return {
        "task_id": tid,
        "status": "queued",
        "target": "warm_index",
        "workspace": ws["path"],
    }


@mcp.tool(task=_SCOUT_TASK)
async def warm_index(
    session_id: str,
    timeout_seconds: float = 120.0,
    ctx: Context | None = None,
    progress: Progress = Progress(),
) -> dict[str, Any]:
    """Isolated index + cache warm pipeline.

    Cursor: sync call + progress; task-capable clients may pass task=True.
    """
    queued = enqueue_warm_index(session_id, timeout_seconds)
    if "error" in queued:
        return queued
    return await _wait_queued_task(str(queued["task_id"]), progress, ctx)


@mcp.tool()
def get_task_status(task_id: str) -> dict[str, Any]:
    """Inspect a SQLite scout task row (optional; tools already wait)."""
    row = get_tasks().get(task_id)
    if row is None:
        return {"error": "not_found", "task_id": task_id}
    return _task_row(row)


# ── scout tools ────────────────────────────────────────────────────────────


@mcp.tool(name="blast_radius")
def blast_radius_tool(
    session_id: str,
    changed_files: list[str],
    include_transitive: bool = False,
) -> dict[str, Any]:
    """Signature blast-radius analysis on the warm session index."""

    def _run(client: Any) -> dict[str, Any]:
        result = blast_radius(
            client, changed_files, include_transitive=include_transitive
        )
        return blast_to_dict(result)

    return _with_lsp_client(session_id, _run)


@mcp.tool()
def list_symbols(session_id: str, file_path: str) -> dict[str, Any]:
    """List symbols in a file (documentSymbol)."""

    def _run(client: Any) -> dict[str, Any]:
        syms = client.document_symbols(file_path)
        return {
            "file_path": file_path,
            "symbols": [
                {
                    "name": s.name,
                    "kind": s.kind,
                    "line": s.line,
                    "character": s.character,
                }
                for s in syms
            ],
            "indexed": client.is_workspace_loaded(),
        }

    return _with_lsp_client(session_id, _run)


@mcp.tool()
def find_references(
    session_id: str,
    file_path: str,
    line: int,
    column: int,
    include_declaration: bool = False,
) -> dict[str, Any]:
    """Find all references to the symbol at position (1-based line/column)."""

    def _run(client: Any) -> dict[str, Any]:
        locs = client.references(file_path, line, column, include_declaration)
        return {
            "references": [
                {"uri": loc.uri, "line": loc.line, "character": loc.character}
                for loc in locs
            ],
            "indexed": client.is_workspace_loaded(),
        }

    return _with_lsp_client(session_id, _run)


@mcp.tool()
def inspect_symbol(
    session_id: str, file_path: str, line: int, column: int
) -> dict[str, Any]:
    """Hover / type info at position."""

    def _run(client: Any) -> dict[str, Any]:
        text = client.hover(file_path, line, column)
        return {"hover": text, "indexed": client.is_workspace_loaded()}

    return _with_lsp_client(session_id, _run)


@mcp.tool()
def go_to_definition(
    session_id: str, file_path: str, line: int, column: int
) -> dict[str, Any]:
    """Go to definition at position."""

    def _run(client: Any) -> dict[str, Any]:
        locs = client.definition(file_path, line, column)
        return {
            "definitions": [
                {"uri": loc.uri, "line": loc.line, "character": loc.character}
                for loc in locs
            ],
            "indexed": client.is_workspace_loaded(),
        }

    return _with_lsp_client(session_id, _run)


@mcp.tool()
def explore_symbol(
    session_id: str, file_path: str, line: int, column: int
) -> dict[str, Any]:
    """Scout composite: hover + definition + references in one call."""

    def _run(client: Any) -> dict[str, Any]:
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

    return _with_lsp_client(session_id, _run)


_CLI_USAGE = """\
usage: agent-lsp [-h] [-V]

Scout LSP MCP server (FastMCP + Rust/PyO3).

With no arguments, starts the MCP server on stdio.

options:
  -h, --help     show this help message and exit
  -V, --version  print package version and exit

Entrypoints: agent-lsp, agent-lsp-real-inspect-mcp (release wheels).
"""


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint: ``--help`` / ``--version``, otherwise start MCP stdio."""
    import sys

    from agent_lsp._version import __version__

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        ensure_data_dirs()
        mcp.run()
        return

    if args[0] in ("-h", "--help") and len(args) == 1:
        print(_CLI_USAGE, end="")
        raise SystemExit(0)
    if args[0] in ("-V", "--version") and len(args) == 1:
        print(__version__)
        raise SystemExit(0)

    print(f"error: unexpected arguments: {' '.join(args)}", file=sys.stderr)
    print(_CLI_USAGE, end="", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
