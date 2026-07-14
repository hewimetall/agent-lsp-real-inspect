# agent-lsp

Scout LSP MCP-сервер: **FastMCP + Rust/PyO3** + **обязательный task support**.

Стек как в [mcp-presentation](https://github.com/hewimetall/mcp-presentation).

## Пакеты

| Пакет | Роль |
|-------|------|
| **`agent-lsp`** | FastMCP + **TaskStore** + scout tools + ScoutWorker |
| **`agent-lsp-state`** | sessions / workspaces / container bindings |
| **`agent-lsp-git`** | gix bare + worktree + clone |
| **`agent-lsp-docker`** | bollard — контейнеры в сессии |

## Task support (обязательно)

`import_project` / `ensure_runtime` / `install_workspace_deps` /
`install_apt_packages` / `warm_index` → `TaskConfig(mode="required")`.

Клиент **должен** вызывать с `task=True`. Очередь — SQLite `state/tasks.db`,
не Docket. Docs: [`docs/guide/tasks.md`](docs/guide/tasks.md) ·
[`docs/guide/workspace-deps.md`](docs/guide/workspace-deps.md) ·
ADL: [`docs/adr/`](docs/adr/README.md).

## Happy path

```text
create_session
  → import_project(source=<git|path>, task=True)
  → checkout_workspace
  → ensure_runtime(language, language_version="3.11", task=True)
  → install_apt_packages([...], task=True)          # optional, no allowlist
  → install_workspace_deps(packages=[...], task=True)  # venv / node_modules / go mod
  → warm_index(..., task=True)
  → blast_radius / explore_symbol   # python → site-packages
  → close_session
```

## Coverage

Python ≠ Rust. Gate = **медиана ≥ 93%** (не среднее).

```bash
make cov-py
make cov-rust
```

## Dev

```bash
uv sync --extra dev
maturin develop                              # TaskStore (core)
(cd packages/agent-lsp-state && maturin develop)
(cd packages/agent-lsp-git && maturin develop)
(cd packages/agent-lsp-docker && maturin develop)
pytest -q
make cov
```

## LSP container images

Four languages from `agent_lsp.runtimes`: **go / python / typescript / rust**.

```bash
make docker-lsp
# or: (cd infra/docker/lsp && ./build.sh)
```

See [`infra/docker/lsp/README.md`](infra/docker/lsp/README.md).
