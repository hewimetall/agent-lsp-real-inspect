# Task-required tools

Long scout ops **require** MCP `task=True` (`TaskConfig(mode="required")`).

## Tools

- `import_project` — git URL or local path → bare repo
- `ensure_runtime` — start LSP; optional `language_version` / `image`
- `install_workspace_deps` — pip/uv/npm/pnpm/go (+ optional apt in same container)
- `install_apt_packages` — apt list with **no allowlist**; persisted for later installs
- `warm_index` — readiness gate before scout

## Client pattern

```python
async with client:
    await client.call_tool(
        "import_project",
        {"project_id": "dramatiq", "source": "https://github.com/Bogdanp/dramatiq.git"},
        task=True,
    )
    # … checkout_workspace …
    await client.call_tool(
        "ensure_runtime",
        {"session_id": sid, "language": "python", "language_version": "3.11"},
        task=True,
    )
    await client.call_tool(
        "install_workspace_deps",
        {
            "session_id": sid,
            "language": "python",
            "language_version": "3.11",
            "packages": ["redis"],
            "apt_packages": ["build-essential"],
        },
        task=True,
    )
    task = await client.call_tool("warm_index", {"session_id": sid}, task=True)
    result = await task.result()
```

Without `task=True` the server rejects the call (required mode).

Durable queue is SQLite `state/tasks.db` (not Docket). See ADR-0001…0004, ADR-0010.
