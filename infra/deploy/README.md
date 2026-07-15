# Deploy: lsp.runmcp.ru

Caddy (auto HTTPS) → bearer check → FastMCP HTTP on `127.0.0.1:8765` (`/mcp`).

```bash
# on server (default ref: v0.1.3)
sudo bash infra/deploy/scripts/bootstrap.sh
# or pin explicitly:
# REPO_REF=v0.1.3 sudo bash infra/deploy/scripts/bootstrap.sh
```

Upgrade an existing install:

```bash
cd /opt/agent-lsp
git fetch --tags origin
git checkout v0.1.3
uv sync --extra dev && uv run make develop
systemctl daemon-reload && systemctl restart agent-lsp
```

Client smoke (remote MCP):

```bash
AGENT_LSP_BEARER_TOKEN=… uv run python scripts/client_prod_smoke.py
```

Client:

```bash
curl -fsS https://lsp.runmcp.ru/health
curl -fsS -H "Authorization: Bearer $AGENT_LSP_BEARER_TOKEN" \
  -H 'Accept: application/json, text/event-stream' \
  https://lsp.runmcp.ru/mcp
```

## Production policy

**Docker-only** LSP runtimes:

| Knob | Value |
|------|--------|
| `/etc/agent-lsp/agent-lsp.env` | `AGENT_LSP_ALLOW_LOCAL=0` |
| `agent-lsp.service` | `Environment=AGENT_LSP_ALLOW_LOCAL=0` (defense in depth) |
| Bootstrap images | `make -C infra/docker/lsp all` + `docker pull python:3.12-bookworm` (fail closed) |
| Mirrors | `AGENT_LSP_MIRRORS` + `AGENT_LSP_MIRRORS_TOML` — sync by hand |

Local pyright/gopls is gated by `AGENT_LSP_ALLOW_LOCAL=1` (tests/dev only).

Heavy trees (Ceph, CPython, …): sync mirrors by hand — see
[`docs/guide/mirrors.md`](../../docs/guide/mirrors.md).
