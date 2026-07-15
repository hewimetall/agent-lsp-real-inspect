"""Language → image / LSP command registry + versioned install bases."""

from __future__ import annotations

import re
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


# Container images: infra/docker/lsp/{go,python,typescript,rust,cpp}/Dockerfile
# python/typescript/rust/cpp images ENTRYPOINT stdio↔TCP bridge on :3737; Cmd = below.
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
        # tsserver path is passed via LSP initialize options (see lsp_settings).
        cmd=["typescript-language-server", "--stdio"],
        local_cmd=["typescript-language-server", "--stdio"],
    ),
    "rust": LanguageRuntime(
        language="rust",
        image="ghcr.io/hewimetall/agent-lsp-rust:latest",
        cmd=["rust-analyzer"],
        local_cmd=["rust-analyzer"],
    ),
    "cpp": LanguageRuntime(
        language="cpp",
        image="ghcr.io/hewimetall/agent-lsp-cpp:latest",
        cmd=["clangd", "--background-index", "--header-insertion=never"],
        local_cmd=["clangd", "--background-index", "--header-insertion=never"],
    ),
}

# LSP image tags when language_version is set (override via ensure_runtime image=).
LSP_VERSION_TAGS: dict[str, dict[str, str]] = {
    "python": {
        "3.11": "ghcr.io/hewimetall/agent-lsp-python:3.11",
        "3.12": "ghcr.io/hewimetall/agent-lsp-python:3.12",
        "3.13": "ghcr.io/hewimetall/agent-lsp-python:3.13",
        "3.14": "ghcr.io/hewimetall/agent-lsp-python:3.14",
    },
    "go": {
        "1.22": "ghcr.io/hewimetall/agent-lsp-go:1.22",
        "1.23": "ghcr.io/hewimetall/agent-lsp-go:1.23",
        "1.24": "ghcr.io/hewimetall/agent-lsp-go:1.24",
    },
    "typescript": {
        "20": "ghcr.io/hewimetall/agent-lsp-typescript:20",
        "22": "ghcr.io/hewimetall/agent-lsp-typescript:22",
    },
}

# Throwaway install bases (Docker Hub) for venv / npm / go mod.
INSTALL_VERSION_IMAGES: dict[str, dict[str, str]] = {
    "python": {
        "3.11": "python:3.11-bookworm",
        "3.12": "python:3.12-bookworm",
        "3.13": "python:3.13-bookworm",
        "3.14": "python:3.14-bookworm",
    },
    "go": {
        "1.22": "golang:1.22-bookworm",
        "1.23": "golang:1.23-bookworm",
        "1.24": "golang:1.24-bookworm",
    },
    "typescript": {
        "20": "node:20-bookworm",
        "22": "node:22-bookworm",
    },
}

INSTALL_DEFAULT_IMAGES: dict[str, str] = {
    "python": "python:3.12-bookworm",
    "go": "golang:1.24-bookworm",
    "typescript": "node:22-bookworm",
    "rust": "rust:1-bookworm",
    "cpp": "debian:bookworm",
}

_VERSION_RE = re.compile(r"^v?(?P<main>\d+(?:\.\d+)?)")


def normalize_language(language: str) -> str:
    key = language.lower().strip()
    if key in {"js", "ts", "javascript"}:
        return "typescript"
    if key in {"c", "cc", "cxx", "c++", "cplusplus", "clang", "clangd"}:
        return "cpp"
    return key


def get_runtime(language: str) -> LanguageRuntime:
    key = normalize_language(language)
    if key not in RUNTIMES:
        known = ", ".join(sorted(RUNTIMES))
        raise ValueError(f"unsupported language {language!r}; known: {known}")
    return RUNTIMES[key]


def _version_key(language: str, version: str) -> str | None:
    raw = (version or "").strip()
    if not raw:
        return None
    m = _VERSION_RE.match(raw)
    if not m:
        return raw
    main = m.group("main")
    # Node versions are major-only in our maps.
    if language == "typescript" and "." in main:
        return main.split(".", 1)[0]
    return main


def resolve_image(
    language: str,
    language_version: str = "",
    image: str = "",
) -> str:
    """Resolve LSP container image. Explicit ``image`` always wins."""
    if image and image.strip():
        return image.strip()
    spec = get_runtime(language)
    lang = normalize_language(language)
    key = _version_key(lang, language_version)
    if key:
        mapped = LSP_VERSION_TAGS.get(lang, {}).get(key)
        if mapped:
            return mapped
        # Fall back to :latest but keep a version-ish tag if publish matrix missing.
        base = spec.image.rsplit(":", 1)[0]
        return f"{base}:{key}"
    return spec.image


def resolve_install_image(language: str, language_version: str = "") -> str:
    lang = normalize_language(language)
    key = _version_key(lang, language_version)
    if key:
        mapped = INSTALL_VERSION_IMAGES.get(lang, {}).get(key)
        if mapped:
            return mapped
        if lang == "python":
            return f"python:{key}-bookworm"
        if lang == "go":
            return f"golang:{key}-bookworm"
        if lang == "typescript":
            return f"node:{key}-bookworm"
    return INSTALL_DEFAULT_IMAGES.get(lang, INSTALL_DEFAULT_IMAGES["python"])
