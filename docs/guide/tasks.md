# Task-aware tools (Cursor-compatible)

Long scout ops enqueue work into SQLite `TaskStore` and **wait** for completion
while emitting progress.

## Tools

- `import_project` — git URL, local path, or `mirror:<id>` → bare repo
  (mirrors must be synced by hand — see [`mirrors.md`](mirrors.md))
- `ensure_runtime` — start LSP; optional `language_version` / `image`
- `install_workspace_deps` — pip/uv/npm/pnpm/go (+ optional apt in same container)
- `install_apt_packages` — apt list with **no allowlist**; persisted for later installs
- `warm_index` — readiness gate before scout

## Modes

| Client | How to call | Progress |
|--------|-------------|----------|
| **Cursor** (no Tasks API) | ordinary `tools/call` | `notifications/progress` (`_meta.progressToken`) |
| Task-capable (FastMCP / vmcp) | `task=True` / `run_task` (optional) | Tasks status **or** progress |

Server advertises `taskSupport: optional` (for Cursor list → `forbidden` so the
IDE does not demand `callToolStream`). Sync calls are accepted.

## Cursor / plain `tools/call`

```python
async with client:
    await client.call_tool(
        "import_project",
        {"project_id": "dramatiq", "source": "https://github.com/Bogdanp/dramatiq.git"},
    )
    # … checkout_workspace …
    await client.call_tool(
        "ensure_runtime",
        {"session_id": sid, "language": "python", "language_version": "3.11"},
    )
    await client.call_tool("warm_index", {"session_id": sid})
```

## Task-capable client (`task=True`)

```python
async with client:
    await client.call_tool(
        "import_project",
        {"project_id": "dramatiq", "source": "https://github.com/Bogdanp/dramatiq.git"},
        task=True,
    )
    task = await client.call_tool("warm_index", {"session_id": sid}, task=True)
    result = await task.result()
```

On initialize the server logs `clientInfo.name` / version / caps
(`journalctl -u agent-lsp | grep mcp_initialize`). Names containing `cursor`
select the progress-first path.

Durable queue is SQLite `state/tasks.db` (not Docket). See ADR-0001…0004, ADR-0010.

Chat request templates (important skills only, **not** MCP `/prompts`):
[`infra/requests/README.md`](../../infra/requests/README.md).

