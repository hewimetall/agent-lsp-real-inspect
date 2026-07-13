# agent-lsp

Scout LSP MCP-сервер: **FastMCP + Rust/PyO3**.

Упрощённый рерайт бывшего Go agent-lsp по стеку
[mcp-presentation](https://github.com/hewimetall/mcp-presentation).

## Пакеты

| Пакет | Роль |
|-------|------|
| **`agent-lsp`** | FastMCP server + scout tools + warm pipeline |
| **`agent-lsp-state`** | sessions / workspaces / container bindings (rusqlite) |
| **`agent-lsp-git`** | GitPort / **gix** — bare + worktree + clone |
| **`agent-lsp-docker`** | ContainerRuntime / **bollard** — контейнеры в сессии |

## Что умеет

1. **LSP** — definition / hover / references / document symbols  
2. **`blast_radius`** — фирменный blast (exports → callers, test/non-test)  
3. **Scout skills** — impact, explore, onboard, refactor, safe-edit, verify  
4. **Git worktree** — реальные исходники в `workspaces/` из bare `projects/`  
5. **Pipeline** — `ensure_runtime` → `warm_index` (изоляция + прогрев кеша)  
6. **Sessions hold containers** — long-lived LSP runtime на сессию  

## Happy path

```text
create_session
  → import_project(project_id, source)          # URL или локальный git path
  → checkout_workspace(session_id, project_id)  # gix worktree
  → ensure_runtime(session_id, "go"|"python"|…)
  → warm_index(session_id)
  → blast_radius / explore_symbol / find_references
  → close_session
```

## Dev

```bash
uv sync --extra dev
(cd packages/agent-lsp-state && maturin develop)
(cd packages/agent-lsp-git && maturin develop)
(cd packages/agent-lsp-docker && maturin develop)
pytest -q
```

```bash
uv run agent-lsp
```

Env:

| Var | Default |
|-----|---------|
| `AGENT_LSP_STATE` | `state` |
| `AGENT_LSP_PROJECTS` | `projects` |
| `AGENT_LSP_WORKSPACES` | `workspaces` |
| `AGENT_LSP_CACHE` | `cache` |

Cursor `mcp.json`:

```json
{
  "mcpServers": {
    "agent-lsp": {
      "command": "uv",
      "args": ["tool", "run", "--from", "/abs/path/to/agent-lsp", "agent-lsp"],
      "env": {
        "AGENT_LSP_STATE": "/abs/data/state",
        "AGENT_LSP_PROJECTS": "/abs/data/projects",
        "AGENT_LSP_WORKSPACES": "/abs/data/workspaces"
      }
    }
  }
}
```

## Архитектура

→ [`docs/architecture/OVERVIEW.md`](docs/architecture/OVERVIEW.md) · ADR [`docs/adr/`](docs/adr/)
