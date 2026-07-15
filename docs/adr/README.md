# Architecture Decision Log (ADL)

Каноническое место фиксации архитектурных решений **agent-lsp** (scout rewrite).

Формат: [Nygard ADR](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions) —
Context / Decision / Consequences. Этот каталог = **ADL** (журнал решений).

| ADR | Код | Статус | Тема |
|-----|-----|--------|------|
| [0001](0001-task-based-async-scout.md) | D1 | Accepted | Task-based async scout pipeline (**required**) |
| [0002](0002-embedded-sqlite-task-store.md) | D1.1 | Accepted | Embedded SQLite для задач |
| [0003](0003-reject-fastmcp-docket-as-queue.md) | D1.2 | Accepted | Docket ≠ durable queue; MCP wait-слой ок |
| [0004](0004-rust-pyo3-taskstore.md) | D1.3 | Accepted | TaskStore через Rust / PyO3 |
| [0005](0005-fastmcp-scout-stack.md) | D2 | Accepted | FastMCP + PyO3 packages |
| [0006](0006-git-worktree-gix.md) | D3 | Accepted | gix bare + worktree, без CLI |
| [0007](0007-session-held-containers.md) | D4 | Accepted | Сессии держат контейнеры (bollard) |
| [0008](0008-coverage-median-split.md) | D5 | Accepted | Coverage: median ≥93%, Rust ≠ Python |
| [0009](0009-lsp-cache-volumes-and-warm-index.md) | D6 | Accepted | Cache volumes + warm_index readiness per LSP |
| [0010](0010-workspace-deps-and-runtime-versions.md) | D7 | Accepted | Language versions + deps/apt install for LSP resolution |
| [0011](0011-local-git-mirrors.md) | D8 | Accepted | Local git mirrors: TOML catalog + manual sync → `mirror:<id>` |
| [0012](0012-runtime-health-worker.md) | D4.1 | Accepted | Separate Rust worker: dead containers → `stale` |

## Как добавить ADR

1. Скопировать [`0000-template.md`](0000-template.md).
2. Следующий номер `NNNN-short-title.md`.
3. Статус: `Proposed` → `Accepted` / `Deprecated` / `Superseded by ADR-XXXX`.
4. Обновить таблицу в этом файле (ADL index).
