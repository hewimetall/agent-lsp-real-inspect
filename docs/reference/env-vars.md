# Environment Variables

All environment variables are optional. agent-lsp works with no configuration.

## Runtime

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_LSP_OUTPUT_FORMAT` | `json` | Output encoding for tool responses. Set to `gcf` to enable [GCF tabular encoding](../guide/gcf-integration.md) (34-44% fewer tokens). |
| `AGENT_LSP_BROKER_TIMEOUT_MS` | `30000` | Timeout in milliseconds for the daemon broker to start. Increase on slow machines or when language servers take long to initialize. |
| `AGENT_LSP_TOKEN` | (none) | Bearer token for HTTP mode authentication. Required when running with `--http`. Never pass on the command line; use this env var instead. |

## Daemon Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_LSP_DAEMON_DIR` | `~/.cache/agent-lsp` | Directory for daemon PID files, socket info, and spawn logs. |

## Debug

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_LSP_LOG_LEVEL` | `warning` | Log level: `debug`, `info`, `warning`, `error`. Also configurable at runtime via the `set_log_level` tool. |
| `AGENT_LSP_AUDIT_LOG` | (none) | Path to write JSON audit log of all tool calls. Useful for debugging and performance analysis. |
