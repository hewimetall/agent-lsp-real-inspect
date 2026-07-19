"""Local-only wrapper (prefer the root wheel's ``python/agent_lsp_docker``)."""

from agent_lsp_docker.agent_lsp_docker import DockerService

__all__ = ["DockerService"]
