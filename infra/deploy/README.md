# Deploy: lsp.runmcp.ru

Caddy (auto HTTPS) → bearer check → FastMCP HTTP on `127.0.0.1:8765` (`/mcp`).

```bash
# on server
sudo bash infra/deploy/scripts/bootstrap.sh
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

Local pyright/gopls is gated by `AGENT_LSP_ALLOW_LOCAL=1` (tests/dev only).