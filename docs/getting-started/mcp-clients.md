# MCP Client Configuration

Copy-paste configs for connecting agent-lsp to your AI tool.

## Claude Code

Add to your project's `.mcp.json` or global `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "agent-lsp": {
      "command": "agent-lsp",
      "args": [],
      "env": {}
    }
  }
}
```

Then run `claude` in your project directory. agent-lsp will appear as an available MCP server. GCF output is enabled by default (30-51% fewer tokens).

## Cursor

Add to `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "agent-lsp": {
      "command": "agent-lsp",
      "args": []
    }
  }
}
```

Restart Cursor after adding the config. agent-lsp tools will appear in the tool picker.

## Windsurf

Add to your Windsurf MCP configuration:

```json
{
  "mcpServers": {
    "agent-lsp": {
      "command": "agent-lsp",
      "args": []
    }
  }
}
```

## Continue.dev

Add to `.continue/config.yaml`:

```yaml
mcpServers:
  - name: agent-lsp
    command: agent-lsp
```

## HTTP Mode (Remote / Docker)

For remote deployments or shared servers, run agent-lsp in HTTP mode:

```bash
agent-lsp --http --port 8080 --token "$AGENT_LSP_TOKEN"
```

Then configure your MCP client to connect via HTTP:

```json
{
  "mcpServers": {
    "agent-lsp": {
      "url": "http://localhost:8080",
      "headers": {
        "Authorization": "Bearer your-secret-token"
      }
    }
  }
}
```

See [Docker documentation](../../DOCKER.md) for containerized deployments.

## Verifying the Connection

After configuring, test with any tool:

```
Use the start_lsp tool to initialize the workspace at /path/to/your/project
```

If the language server starts successfully, agent-lsp is connected and ready.
