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
