#!/usr/bin/env bash
# Stamp all publishable packages with VERSION from a release tag (vX.Y.Z → X.Y.Z).
# Also switches the main distribution name to the PyPI project
# ``agent-lsp-real-inspect-mcp`` (``agent-lsp`` is already taken upstream)
# and pins sibling deps so wheels resolve on PyPI (no uv workspace sources).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

raw="${1:-}"
if [[ -z "$raw" ]]; then
  echo "usage: $0 <version|vX.Y.Z>" >&2
  exit 2
fi
VERSION="${raw#v}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([a-zA-Z0-9.-]*)?$ ]]; then
  echo "invalid version: $VERSION (expected semver, optional pre-release)" >&2
  exit 2
fi

PYPI_NAME="agent-lsp-real-inspect-mcp"

python3 - "$VERSION" "$PYPI_NAME" <<'PY'
import pathlib
import re
import sys

version, pypi_name = sys.argv[1], sys.argv[2]
root = pathlib.Path(".")

def set_project_version(path: pathlib.Path, *, rename: str | None = None, pin_siblings: bool = False) -> None:
    text = path.read_text(encoding="utf-8")
    text2, n = re.subn(
        r'(?m)^(version\s*=\s*)"[^"]*"',
        rf'\1"{version}"',
        text,
        count=1,
    )
    if n != 1:
        raise SystemExit(f"could not set version in {path}")
    if rename:
        text2, n = re.subn(
            r'(?m)^(name\s*=\s*)"agent-lsp"',
            rf'\1"{rename}"',
            text2,
            count=1,
        )
        if n != 1:
            raise SystemExit(f"could not rename project in {path}")
    if pin_siblings:
        for dep in ("agent-lsp-state", "agent-lsp-git", "agent-lsp-docker"):
            text2, n = re.subn(
                rf'(?m)^(\s*)"{dep}"\s*,?\s*$',
                rf'\1"{dep}=={version}",',
                text2,
                count=1,
            )
            if n != 1:
                raise SystemExit(f"could not pin {dep} in {path}")
        # Ensure uvx finds a console script matching the distribution name.
        if 'agent-lsp-real-inspect-mcp = "agent_lsp.server:main"' not in text2:
            text2 = text2.replace(
                'agent-lsp = "agent_lsp.server:main"',
                'agent-lsp = "agent_lsp.server:main"\n'
                'agent-lsp-real-inspect-mcp = "agent_lsp.server:main"',
                1,
            )
    path.write_text(text2, encoding="utf-8")
    # ASCII-only: Windows runners default to cp1252 and choke on "→".
    print(f"OK {path} -> {version}" + (f" name={rename}" if rename else ""))

set_project_version(root / "pyproject.toml", rename=pypi_name, pin_siblings=True)
for rel in (
    "packages/agent-lsp-state/pyproject.toml",
    "packages/agent-lsp-git/pyproject.toml",
    "packages/agent-lsp-docker/pyproject.toml",
):
    set_project_version(root / rel)
PY

echo "release version stamped: $VERSION (PyPI name: $PYPI_NAME)"
