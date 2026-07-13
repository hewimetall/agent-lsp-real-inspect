#!/usr/bin/env bash
# Build one or all agent-lsp runtime images.
# Usage:
#   ./build.sh              # build all
#   ./build.sh go rust      # build subset
#   REGISTRY=ghcr.io/me TAG=dev ./build.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

REGISTRY="${REGISTRY:-ghcr.io/hewimetall}"
TAG="${TAG:-latest}"

if [[ $# -eq 0 ]]; then
  LANGS=(go python typescript rust)
else
  LANGS=("$@")
fi

for lang in "${LANGS[@]}"; do
  dockerfile="$ROOT/$lang/Dockerfile"
  if [[ ! -f "$dockerfile" ]]; then
    echo "unknown language: $lang (no $dockerfile)" >&2
    exit 1
  fi
  image="${REGISTRY}/agent-lsp-${lang}:${TAG}"
  echo "==> building $image"
  docker build -f "$dockerfile" -t "$image" "$ROOT"
done

echo "done."
