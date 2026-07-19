"""agent-lsp — FastMCP scout server (sessions + worktrees + warm LSP + tasks)."""

from agent_lsp._version import __version__
from agent_lsp.server import main, mcp

__all__ = ["__version__", "main", "mcp"]
