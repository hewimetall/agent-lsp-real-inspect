# vmcp ↔ agent-lsp wiring examples

| File | Role |
|------|------|
| [`registry.agent-lsp.json`](registry.agent-lsp.json) | Minimal vmcp upstream registry (stdio → `uv run agent-lsp`) |
| [`specs/agent-lsp.json`](specs/agent-lsp.json) | Sidecar: `task_support` for long tools + readOnly hints |

Replace every `/ABS/PATH/TO/agent-lsp-real-inspect` before use.

Operator guide: [`docs/guide/runbook-with-vmcp.md`](../../docs/guide/runbook-with-vmcp.md).
