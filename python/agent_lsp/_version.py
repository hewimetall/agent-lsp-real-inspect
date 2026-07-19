"""Distribution version resolution (dev name vs PyPI release name)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

# Release renames the dist to ``agent-lsp-real-inspect-mcp`` (``agent-lsp`` is
# taken upstream). Prefer the release name, fall back to the workspace name.
_DIST_NAMES = ("agent-lsp-real-inspect-mcp", "agent-lsp")


def package_version() -> str:
    for dist in _DIST_NAMES:
        try:
            return version(dist)
        except PackageNotFoundError:
            continue
    return "0.0.0+unknown"


__version__ = package_version()
