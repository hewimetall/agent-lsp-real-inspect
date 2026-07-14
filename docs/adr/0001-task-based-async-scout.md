# ADR-0001: Task-based async scout pipeline (required)

- Status: Accepted
- Date: 2026-07-13
- Code: D1
- Deciders: product / architecture
- Relates: ADR-0002, ADR-0003, ADR-0004
- Inspired by: mcp-presentation ADR-0001

## Context

`import_project`, `ensure_runtime`, `warm_index` могут занимать секунды–минуты
(clone, Docker pull/start, LSP indexing). Синхронный MCP-tool блокирует клиента и
ломается на таймаутах.

## Decision

Долгие scout-операции — **асинхронные задачи**:

1. Tool ставит задачу в SQLite `TaskStore` и будит `ScoutWorker`.
2. Tool **ждёт** terminal status (`done` / `error`) через `await_sqlite_task`.
3. FastMCP `TaskConfig(mode="optional")` — task-capable clients **may** call with
   `task=True` (SEP-1686). Clients **without** Tasks (notably **Cursor**) use
   ordinary `tools/call` + `notifications/progress`. Middleware rewrites
   advertised `taskSupport` to `forbidden` for Cursor so the IDE does not demand
   `callToolStream`.
4. `get_task_status(task_id)` — инспекция SQLite-строки (опционально).

# ADR-0001 targets (extended by ADR-0010)
Targets: `import_project` | `ensure_runtime` | `warm_index` |
`install_workspace_deps` | `install_apt_packages`.

## Consequences

### Positive

- Durable queue переживает рестарт (ADR-0002).
- Protocol-native progress для агентов.
- Тот же паттерн, что mcp-presentation builds.

### Negative / risks

- Клиенты без Tasks (Cursor) идут sync+progress; task-capable — по желанию `task=True`.
- Два ID: MCP protocol task id и наш SQLite `task_id` (связь в progress message).

## Alternatives considered

| Option | Why not |
|--------|---------|
| Синхронный warm_index без progress | Таймауты / плохой UX |
| `mode=required` only | Cursor (нет Tasks API) получает `-32600` |
| Только polling `get_task_status` | Плохой UX без notifications |
