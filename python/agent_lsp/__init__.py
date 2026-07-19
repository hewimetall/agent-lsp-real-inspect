"""agent-lsp — FastMCP scout server (sessions + worktrees + warm LSP + tasks)."""

from __future__ import annotations

from typing import Any

from agent_lsp._version import __version__
from agent_lsp.server import main, mcp

__all__ = [
    "DockerService",
    "GitService",
    "StateStore",
    "TaskStore",
    "__version__",
    "main",
    "mcp",
]


def __getattr__(name: str) -> Any:
    # Lazy: keeps ``import agent_lsp`` light and avoids init-order issues.
    if name in {"TaskStore", "StateStore", "GitService", "DockerService"}:
        from agent_lsp import _tasks

        return getattr(_tasks, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
