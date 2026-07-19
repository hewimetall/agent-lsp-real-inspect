# Docs

| Path | Content |
|------|---------|
| [architecture/OVERVIEW.md](architecture/OVERVIEW.md) | Stack + task pipeline |
| [architecture/c4.md](architecture/c4.md) | **C4** Context / Container / Component |
| [adr/](adr/README.md) | **ADL** — Architecture Decision Log (ADR index) |
| [guide/tasks.md](guide/tasks.md) | How to call task-required tools + MCP prompts |
| [guide/coverage.md](guide/coverage.md) | Median coverage gates |
| [guide/lsp-cache-and-indexing.md](guide/lsp-cache-and-indexing.md) | LSP cache/indexing research (go/python/typescript/rust) |
| [guide/workspace-deps.md](guide/workspace-deps.md) | Versioned runtimes + deps/apt |
| [guide/workspace-deps-validation.md](guide/workspace-deps-validation.md) | **FIXED** validation report (vmcp GraphQL aliases) |
| [guide/runbook-solo.md](guide/runbook-solo.md) | Raise agent-lsp alone (step-by-step) |
| [guide/runbook-with-vmcp.md](guide/runbook-with-vmcp.md) | Raise agent-lsp **with** vmcp gateway |
| [guide/mirrors.md](guide/mirrors.md) | Local git mirrors (TOML + manual sync) |
| [guide/pypi-release.md](guide/pypi-release.md) | **PyPI by tag** — `uvx agent-lsp-real-inspect-mcp` |
| [../infra/requests/](../infra/requests/README.md) | Important chat request templates (not MCP `/prompts`) |

Examples: [`infra/vmcp/`](../infra/vmcp/) — registry + sidecar for vmcp.

Skills live in `/skills` (impact, explore, onboard, mirror, refactor, safe-edit, verify).
Templates for chat: `/infra/requests` (onboard, mirror, explore, impact, safe-edit, verify).
