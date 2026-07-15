# ADR-0003: Reject FastMCP Docket as durable queue

- Status: Accepted
- Date: 2026-07-13
- Code: D1.2
- Relates: ADR-0001, ADR-0002
- Inspired by: mcp-presentation ADR-0003

## Context

FastMCP background tasks (`task=True`) используют **Docket**. Backends:

| Backend | Persistent | Fits ADR-0002 |
|---------|------------|---------------|
| `memory://` | no | no (as queue) |
| Redis | yes | no (external) |
| SQLite | — | does not exist |

## Decision

**Не использовать** Docket как durable scout queue.

Очередь = наш SQLite TaskStore + `ScoutWorker`.

**Разрешено / обязательно** FastMCP `task=True` как MCP protocol wait-слой:

1. Tool → `TaskStore.submit` (наш `task_id`).
2. Worker исполняет.
3. Tool ждёт SQLite и зеркалит статусы через `Progress` → `notifications/tasks/status`.
4. `mode="optional"` для long tools (Cursor без Tasks → sync+progress).

Мост: `python/agent_lsp/task_bridge.py`.

## Consequences

- Durable state в SQLite; protocol UX через Docket memory.
- Обрыв MCP-wait при рестарте сервера; сама задача в SQLite дожимается worker'ом.
