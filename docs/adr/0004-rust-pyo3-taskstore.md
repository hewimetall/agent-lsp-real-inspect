# ADR-0004: TaskStore via Rust / PyO3

- Status: Accepted
- Date: 2026-07-13
- Code: D1.3

## Context

Нужен быстрый, тестируемый TaskStore рядом с state/git/docker PyO3-пакетами.

## Decision

`TaskStore` на Rust (rusqlite), экспорт через PyO3 / maturin:

- Модуль: `agent_lsp._tasks.TaskStore`
- Crate: `agent-lsp-core` (repo root `src/lib.rs`)

```python
from agent_lsp._tasks import TaskStore
store = TaskStore("state/tasks.db")
```

## Consequences

- Единый стиль с `agent-lsp-state` / git / docker.
- Сборка: `maturin develop` в корне.
