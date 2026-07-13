"""Language → image / LSP command registry."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageRuntime:
    language: str
    image: str
    # Command inside container: language server listening on TCP 3737 (or stdio via wrapper).
    cmd: list[str]
    # Local fallback command when Docker is unavailable (tests / bare metal).
    local_cmd: list[str]
    container_workdir: str = "/workspace"


# Container images: infra/docker/lsp/{go,python,typescript,rust}/Dockerfile
# python/typescript/rust images ENTRYPOINT stdio↔TCP bridge on :3737; Cmd = below.
RUNTIMES: dict[str, LanguageRuntime] = {
    "go": LanguageRuntime(
        language="go",
        image="ghcr.io/hewimetall/agent-lsp-go:latest",
        cmd=["gopls", "serve", "-listen=0.0.0.0:3737", "-rpc.trace"],
        local_cmd=["gopls", "serve", "-listen=127.0.0.1:{port}"],
    ),
    "python": LanguageRuntime(
        language="python",
        image="ghcr.io/hewimetall/agent-lsp-python:latest",
        # Image ENTRYPOINT = stdio_tcp_bridge; this Cmd is the stdio LSP.
        cmd=["pyright-langserver", "--stdio"],
        local_cmd=["pyright-langserver", "--stdio"],
    ),
    "typescript": LanguageRuntime(
        language="typescript",
        image="ghcr.io/hewimetall/agent-lsp-typescript:latest",
        cmd=["typescript-language-server", "--stdio"],
        local_cmd=["typescript-language-server", "--stdio"],
    ),
    "rust": LanguageRuntime(
        language="rust",
        image="ghcr.io/hewimetall/agent-lsp-rust:latest",
        cmd=["rust-analyzer"],
        local_cmd=["rust-analyzer"],
    ),
}


def get_runtime(language: str) -> LanguageRuntime:
    key = language.lower().strip()
    if key not in RUNTIMES:
        known = ", ".join(sorted(RUNTIMES))
        raise ValueError(f"unsupported language {language!r}; known: {known}")
    return RUNTIMES[key]
