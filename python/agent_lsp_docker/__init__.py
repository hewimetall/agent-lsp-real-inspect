"""Compat package: DockerService ships in the main ``agent_lsp._tasks`` extension."""

from agent_lsp_docker._native import DockerService

__all__ = ["DockerService"]
