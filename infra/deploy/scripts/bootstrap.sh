#!/usr/bin/env bash
# Bootstrap agent-lsp + Caddy on a fresh Ubuntu host (lsp.runmcp.ru).
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/hewimetall/agent-lsp-real-inspect.git}"
REPO_REF="${REPO_REF:-v0.1.5}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/agent-lsp}"
DATA_ROOT="${DATA_ROOT:-/var/lib/agent-lsp}"
DOMAIN="${DOMAIN:-lsp.runmcp.ru}"
BUILD_LSP_IMAGES="${BUILD_LSP_IMAGES:-1}"

export DEBIAN_FRONTEND=noninteractive

echo "==> packages"
apt-get update -qq
apt-get install -y -qq \
  ca-certificates curl git build-essential pkg-config \
  caddy docker.io docker-compose-v2 \
  python3 python3-venv python3-pip

systemctl enable --now docker || true

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:/root/.local/bin:$PATH"
fi
export PATH="$HOME/.local/bin:/root/.local/bin:$PATH"

if ! command -v rustc >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
fi
# shellcheck disable=SC1091
source "$HOME/.cargo/env"

echo "==> clone ${REPO_URL}@${REPO_REF}"
mkdir -p "$(dirname "$INSTALL_ROOT")"
if [[ -d "$INSTALL_ROOT/.git" ]]; then
  git -C "$INSTALL_ROOT" fetch origin
  git -C "$INSTALL_ROOT" checkout "$REPO_REF"
  git -C "$INSTALL_ROOT" pull --ff-only origin "$REPO_REF" || true
else
  rm -rf "$INSTALL_ROOT"
  git clone --branch "$REPO_REF" --depth 1 "$REPO_URL" "$INSTALL_ROOT"
fi
cd "$INSTALL_ROOT"

echo "==> python / maturin"
export PATH="$(pwd)/.venv/bin:$HOME/.local/bin:/root/.local/bin:$PATH"
uv sync --extra dev
# Prefer uv-run maturin so PATH need not include .venv yet
uv run make develop || make develop

if [[ "$BUILD_LSP_IMAGES" == "1" ]]; then
  echo "==> build LSP Docker images (all languages + python 3.12 tag)"
  make -C infra/docker/lsp all
  make -C infra/docker/lsp python-versions PYTHON_VERSIONS="3.12"
  # Base image for install_workspace_deps / apt bootstrap — fail closed
  docker pull python:3.12-bookworm
fi

mkdir -p "$DATA_ROOT"/{state,projects,workspaces,cache,mirrors} /etc/agent-lsp

if [[ ! -f /etc/agent-lsp/bearer.env ]]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  umask 077
  printf 'AGENT_LSP_BEARER_TOKEN=%s\n' "$TOKEN" >/etc/agent-lsp/bearer.env
  echo "Generated bearer token → /etc/agent-lsp/bearer.env"
else
  # shellcheck disable=SC1091
  source /etc/agent-lsp/bearer.env
  TOKEN="${AGENT_LSP_BEARER_TOKEN:?}"
fi

cat >/etc/agent-lsp/agent-lsp.env <<ENVEOF
AGENT_LSP_STATE=${DATA_ROOT}/state
AGENT_LSP_PROJECTS=${DATA_ROOT}/projects
AGENT_LSP_WORKSPACES=${DATA_ROOT}/workspaces
AGENT_LSP_CACHE=${DATA_ROOT}/cache
AGENT_LSP_MIRRORS=${DATA_ROOT}/mirrors
AGENT_LSP_MIRRORS_TOML=${INSTALL_ROOT}/infra/mirrors/mirrors.toml
# Production: Docker-only LSP / deps (never enable AGENT_LSP_ALLOW_LOCAL here)
AGENT_LSP_ALLOW_LOCAL=0
AGENT_LSP_RUNTIME_WORKER_INTERVAL_SECS=15
FASTMCP_TRANSPORT=http
FASTMCP_HOST=127.0.0.1
FASTMCP_PORT=8765
FASTMCP_SHOW_SERVER_BANNER=false
ENVEOF
chmod 600 /etc/agent-lsp/agent-lsp.env
# caddy unit runs as user `caddy` — needs read access to the bearer env
chown root:caddy /etc/agent-lsp/bearer.env 2>/dev/null || chown root:root /etc/agent-lsp/bearer.env
chmod 640 /etc/agent-lsp/bearer.env

echo "==> mirrors: sync by hand when needed"
echo "    uv run python scripts/mirror-sync.py list"
echo "    uv run python scripts/mirror-sync.py sync ceph minio …"
install -m 0644 infra/deploy/caddy/Caddyfile /etc/caddy/Caddyfile
# Ensure caddy loads bearer env
mkdir -p /etc/systemd/system/caddy.service.d
install -m 0644 infra/deploy/systemd/caddy.service.d-override.conf \
  /etc/systemd/system/caddy.service.d/override.conf
install -m 0644 infra/deploy/systemd/agent-lsp.service /etc/systemd/system/agent-lsp.service
install -m 0644 infra/deploy/systemd/agent-lsp-runtime-worker.service \
  /etc/systemd/system/agent-lsp-runtime-worker.service

echo "==> build runtime health worker"
cargo build --release -p agent-lsp-runtime-worker \
  --manifest-path packages/agent-lsp-runtime-worker/Cargo.toml
# Install next to release target expected by the unit (workspace-local target/)
mkdir -p "$INSTALL_ROOT/target/release"
install -m 0755 \
  packages/agent-lsp-runtime-worker/target/release/agent-lsp-runtime-worker \
  "$INSTALL_ROOT/target/release/agent-lsp-runtime-worker" \
  2>/dev/null \
  || install -m 0755 \
    target/release/agent-lsp-runtime-worker \
    "$INSTALL_ROOT/target/release/agent-lsp-runtime-worker"

# Open HTTP/HTTPS if ufw is active (ACME + serve)
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi 'Status: active'; then
  ufw allow 80/tcp || true
  ufw allow 443/tcp || true
fi

systemctl daemon-reload
systemctl enable --now agent-lsp
systemctl enable --now agent-lsp-runtime-worker
systemctl enable --now caddy
systemctl restart agent-lsp
systemctl restart agent-lsp-runtime-worker
systemctl restart caddy

echo "==> waiting for local MCP"
for i in $(seq 1 60); do
  if curl -fsS -o /dev/null "http://127.0.0.1:8765/mcp" -H 'Accept: application/json, text/event-stream' -X POST \
    -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"boot","version":"0"}}}' \
    2>/dev/null || curl -fsS -o /dev/null "http://127.0.0.1:8765/mcp" 2>/dev/null; then
    break
  fi
  # accept any HTTP response from listening socket
  if ss -ltn | grep -q ':8765'; then
    break
  fi
  sleep 1
done

echo "==> smoke"
curl -fsS "https://${DOMAIN}/health" || curl -fsS "http://${DOMAIN}/health" || true
code="$(curl -s -o /dev/null -w '%{http_code}' "https://${DOMAIN}/mcp" || true)"
echo "without token → HTTP ${code} (expect 401)"
code2="$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${TOKEN}" "https://${DOMAIN}/mcp" || true)"
echo "with token → HTTP ${code2}"

echo
echo "Bearer token: ${TOKEN}"
echo "MCP URL: https://${DOMAIN}/mcp"
