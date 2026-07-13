# ADR-0002: Embedded SQLite task store

- Status: Accepted
- Date: 2026-07-13
- Code: D1.1
- Relates: ADR-0001, ADR-0004

## Context

Нужно persistent хранилище задач без Redis/внешних сервисов.

## Decision

Задачи в **embedded SQLite**: `state/tasks.db` (отдельно от `state/sessions.db`).

Схема: `task_id`, `session_id`, `workspace`, `target`, `status`, `artifact`,
`logs`, `error`, `created_at`, `updated_at`.

Статусы: `queued` → `running` → `done` | `error`.

API владеет Rust `TaskStore` (ADR-0004), не Python `sqlite3`.

## Consequences

- Ноль внешних deps для queue.
- Один writer; горизонтальный multi-host worker — вне v1.
