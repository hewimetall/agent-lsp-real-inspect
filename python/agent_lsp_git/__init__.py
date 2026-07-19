"""Compat package: GitService ships in the main ``agent_lsp._tasks`` extension."""

from agent_lsp_git._native import GitService

__all__ = ["GitService"]
