"""Detect MCP clients that cannot use SEP-1686 Tasks (e.g. Cursor).

Cursor talks MCP via ordinary ``tools/call`` and can surface
``notifications/progress`` (``_meta.progressToken``), but it does **not**
implement experimental Tasks / ``callToolStream``. Advertising
``taskSupport: required`` makes Cursor refuse the call before execution.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("agent_lsp.client")

# Long tools that previously used TaskConfig(mode="required").
SCOUT_LONG_TOOLS = frozenset(
    {
        "import_project",
        "ensure_runtime",
        "install_workspace_deps",
        "install_apt_packages",
        "warm_index",
    }
)


def _env_force_progress() -> bool:
    raw = (os.environ.get("AGENT_LSP_FORCE_PROGRESS_CLIENTS") or "").strip().lower()
    return raw in {"1", "true", "yes", "all"}


def client_info_dict(ctx: Any | None) -> dict[str, Any]:
    """Best-effort ``{name, version, title}`` from the MCP session."""
    if ctx is None:
        return {}
    session = getattr(ctx, "session", None)
    params = getattr(session, "client_params", None) if session is not None else None
    info = getattr(params, "clientInfo", None) if params is not None else None
    if info is None:
        return {}
    out: dict[str, Any] = {}
    for key in ("name", "version", "title"):
        val = getattr(info, key, None)
        if val is not None:
            out[key] = val
    return out


def client_capabilities_dict(ctx: Any | None) -> dict[str, Any]:
    if ctx is None:
        return {}
    session = getattr(ctx, "session", None)
    params = getattr(session, "client_params", None) if session is not None else None
    caps = getattr(params, "capabilities", None) if params is not None else None
    if caps is None:
        return {}
    # Pydantic model → plain dict when available.
    dump = getattr(caps, "model_dump", None)
    if callable(dump):
        try:
            return dict(dump(exclude_none=True))
        except Exception:
            pass
    return {"raw": repr(caps)}


def client_has_tasks_capability(ctx: Any | None) -> bool:
    """True when initialize advertised ``capabilities.tasks``."""
    if ctx is None:
        return False
    session = getattr(ctx, "session", None)
    params = getattr(session, "client_params", None) if session is not None else None
    caps = getattr(params, "capabilities", None) if params is not None else None
    if caps is None:
        return False
    return getattr(caps, "tasks", None) is not None


def is_cursor_client(ctx: Any | None = None, *, name: str | None = None) -> bool:
    """Match Cursor IDE / agent by ``clientInfo.name`` (substring ``cursor``)."""
    label = name
    if label is None:
        label = str(client_info_dict(ctx).get("name") or "")
    return "cursor" in label.lower()


def prefers_progress_over_tasks(ctx: Any | None = None, *, name: str | None = None) -> bool:
    """Clients that should get sync ``tools/call`` + progress, not required Tasks.

    - Cursor (by name)
    - Any client without ``capabilities.tasks``
    - ``AGENT_LSP_FORCE_PROGRESS_CLIENTS=1`` (ops override)
    """
    if _env_force_progress():
        return True
    if is_cursor_client(ctx, name=name):
        return True
    # No session yet (e.g. list before init finished) → keep advertised optional.
    if ctx is None:
        return False
    session = getattr(ctx, "session", None)
    params = getattr(session, "client_params", None) if session is not None else None
    if params is None:
        return False
    return not client_has_tasks_capability(ctx)


def log_client_initialize(
    *,
    name: str | None,
    version: str | None,
    capabilities: Any | None,
) -> None:
    """Structured log line for operators (journalctl -u agent-lsp)."""
    caps_summary: dict[str, Any] = {}
    if capabilities is not None:
        for key in ("roots", "sampling", "elicitation", "experimental", "tasks"):
            val = getattr(capabilities, key, None)
            if val is not None:
                caps_summary[key] = True if key != "experimental" else val
    progress_first = prefers_progress_over_tasks(name=name or "")
    logger.info(
        "mcp_initialize clientInfo.name=%r version=%r progress_first=%s caps=%s",
        name,
        version,
        progress_first,
        caps_summary,
    )
