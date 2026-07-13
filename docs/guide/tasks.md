# Task-required tools

Long scout ops **require** MCP `task=True` (`TaskConfig(mode="required")`).

## Tools

- `import_project`
- `ensure_runtime`
- `warm_index`

## Client pattern

```python
async with client:
    task = await client.call_tool("warm_index", {"session_id": sid}, task=True)
    # notifications/tasks/status carry: task_id=<uuid> status=queued|running|done|error
    result = await task.result()
```

Without `task=True` the server rejects the call (required mode).

Durable queue is SQLite `state/tasks.db` (not Docket). See ADR-0001…0004.
