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
3. FastMCP `TaskConfig(mode="required")` — клиент **обязан** вызывать с `task=True`
   (SEP-1686 wait + `notifications/tasks/status`).
4. `get_task_status(task_id)` — инспекция SQLite-строки (опционально).

Targets v1: `import_project` | `ensure_runtime` | `warm_index`.

## Consequences

### Positive

- Durable queue переживает рестарт (ADR-0002).
- Protocol-native progress для агентов.
- Тот же паттерн, что mcp-presentation builds.

### Negative / risks

- Клиенты без `task=True` не смогут вызвать required tools.
- Два ID: MCP protocol task id и наш SQLite `task_id` (связь в progress message).

## Alternatives considered

| Option | Why not |
|--------|---------|
| Синхронный warm_index | Таймауты MCP |
| `mode=optional` | Не «обязательный» task support |
| Только polling `get_task_status` | Плохой UX без notifications |
