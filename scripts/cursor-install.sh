#!/usr/bin/env bash
# Cursor cloud-agent update/install (hot-swap friendly, idempotent).
# Wired from .cursor/environment.json → "install".
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/.local/bin:/usr/local/cargo/bin:${PATH}"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi

# libpython symlink for PyO3 / llvm-cov when -dev package is missing
mkdir -p .libs
if [[ ! -e .libs/libpython3.12.so ]]; then
  for cand in \
    /usr/lib/x86_64-linux-gnu/libpython3.12.so.1.0 \
    /usr/lib/python3.12/config-3.12-x86_64-linux-gnu/libpython3.12.so; do
    if [[ -e "$cand" ]]; then
      ln -sfn "$cand" .libs/libpython3.12.so
      break
    fi
  done
fi

export LIBRARY_PATH="${ROOT}/.libs:${LIBRARY_PATH:-}"
export LD_LIBRARY_PATH="${ROOT}/.libs:${LD_LIBRARY_PATH:-}"
export PYO3_PYTHON="${ROOT}/.venv/bin/python"

uv sync --extra dev

if ! command -v maturin >/dev/null 2>&1; then
  uv tool install maturin >/dev/null 2>&1 || uv pip install maturin
fi

echo "==> maturin develop (single wheel: state/git/docker path-deps)"
maturin develop --uv

echo "OK: cursor-install hot-swap update complete"
