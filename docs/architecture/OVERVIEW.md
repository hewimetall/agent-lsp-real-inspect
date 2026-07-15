# Architecture overview — scout rewrite

```text
                 ┌──────────────────────────────┐
                 │     FastMCP (Python)         │
                 │  agent-lsp + TaskStore wait  │
                 │  task=True REQUIRED (long)   │
                 └──────────────┬───────────────┘
        ┌───────────────────────┼────────────────────────┐
        ▼                       ▼                        ▼
┌───────────────┐      ┌───────────────┐       ┌────────────────┐
│ TaskStore     │      │ agent-lsp-git │       │ agent-lsp-docker│
│ (rusqlite)    │      │ gix worktree  │       │ bollard         │
│ ScoutWorker   │      │               │       │ session-held    │
└───────────────┘      └───────────────┘       └────────────────┘
        │
        ▼
┌───────────────┐
│ agent-lsp-state│ sessions + container bindings
└───────────────┘
```

## Task pipeline (mandatory)

Long tools use `TaskConfig(mode="optional")` (Cursor → sync + progress):

| Tool | Target | Notes |
|------|--------|-------|
| `import_project` | `import_project` | gix clone/import |
| `ensure_runtime` | `ensure_runtime` | container or local LSP (+ language_version) |
| `install_workspace_deps` | `install_workspace_deps` | venv / node_modules / go mod (+ optional apt) |
| `install_apt_packages` | `install_apt_packages` | apt bootstrap, no allowlist |
| `warm_index` | `warm_index` | index + cache warm |

```text
call_tool(..., task=True)
  → TaskStore.submit → ScoutWorker.claim_next
  → await_sqlite_task (+ Progress notifications)
  → done | error
```

`get_task_status(task_id)` — optional SQLite inspection.

ADL/ADR: [`docs/adr/`](../adr/README.md)

## Coverage

- **Python** and **Rust** are separate.
- Gate = **median** line coverage ≥ **93%** (not mean).
- `make cov-py` / `make cov-rust`
