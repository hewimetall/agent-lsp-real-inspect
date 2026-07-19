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

## Runbooks

| Doc | When |
|-----|------|
| [`docs/guide/runbook-solo.md`](docs/guide/runbook-solo.md) | Поднять agent-lsp **самостоятельно** |
| [`docs/guide/runbook-with-vmcp.md`](docs/guide/runbook-with-vmcp.md) | Поднять **вместе с vmcp** (GraphQL aliases) |
| [`docs/guide/workspace-deps-validation.md`](docs/guide/workspace-deps-validation.md) | Зафиксированный validation-отчёт |
| [`infra/vmcp/`](infra/vmcp/) | Пример `registry.json` + sidecar |

```bash
./scripts/verify_runbook.sh solo
./scripts/verify_runbook.sh with-vmcp   # + checks vmcp source / optional :8765 health
```

## Install (PyPI / uv)

Published on tags `v*` as **`agent-lsp-real-inspect-mcp`**
(upstream already owns the PyPI name `agent-lsp`).

```bash
uvx agent-lsp-real-inspect-mcp
# or
uv tool install agent-lsp-real-inspect-mcp
agent-lsp
```

Cut a release: `git tag -a v0.1.6 -m v0.1.6 && git push origin v0.1.6`  
Setup (Trusted Publisher + env `pypi`): [`docs/guide/pypi-release.md`](docs/guide/pypi-release.md).

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

Languages from `agent_lsp.runtimes`: **go / python / typescript / rust / cpp**
(clangd + `compile_commands.json` for C/C++).

```bash
make docker-lsp
# or: (cd infra/docker/lsp && ./build.sh)
```

See [`infra/docker/lsp/README.md`](infra/docker/lsp/README.md).

## Runtime health

Dead Docker LSP containers are demoted to `stale` by
`agent-lsp-runtime-worker` (ADR-0012); the hub also checks `is_running`
before reuse so scout tools do not hit `Broken pipe`.
