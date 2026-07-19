#!/usr/bin/env bash
# Stamp the single publishable package with VERSION from a release tag
# (vX.Y.Z → X.Y.Z) and rename the dist to ``agent-lsp-real-inspect-mcp``
# (``agent-lsp`` is already taken upstream).
#
# Sibling Rust crates (state/git/docker) ship inside this one wheel — no
# separate PyPI projects / Trusted Publishers.
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
path = pathlib.Path("pyproject.toml")
text = path.read_text(encoding="utf-8")
text2, n = re.subn(
    r'(?m)^(version\s*=\s*)"[^"]*"',
    rf'\1"{version}"',
    text,
    count=1,
)
if n != 1:
    raise SystemExit(f"could not set version in {path}")
text2, n = re.subn(
    r'(?m)^(name\s*=\s*)"agent-lsp"',
    rf'\1"{pypi_name}"',
    text2,
    count=1,
)
if n != 1:
    raise SystemExit(f"could not rename project in {path}")
# Ensure uvx finds a console script matching the distribution name.
if 'agent-lsp-real-inspect-mcp = "agent_lsp.server:main"' not in text2:
    text2 = text2.replace(
        'agent-lsp = "agent_lsp.server:main"',
        'agent-lsp = "agent_lsp.server:main"\n'
        'agent-lsp-real-inspect-mcp = "agent_lsp.server:main"',
        1,
    )
path.write_text(text2, encoding="utf-8")
# ASCII-only: Windows runners default to cp1252 and choke on non-ASCII.
print(f"OK {path} -> {version} name={pypi_name}")
PY

echo "release version stamped: $VERSION (PyPI name: $PYPI_NAME)"
