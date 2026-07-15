# Runbook: поднять agent-lsp (solo)

Пошаговый подъём **без** vmcp. Клиент ходит в FastMCP напрямую (`uv run agent-lsp`
или in-process `Client(mcp)`).

## 0. Prerequisites

| Need | Check |
|------|-------|
| Python ≥ 3.12 + uv | `uv --version` |
| Rust + maturin (PyO3 packages) | `rustc --version` · `uv run maturin --version` |
| **Docker (required for LSP / deps)** | `docker info` |
| LSP images | `docker images 'ghcr.io/hewimetall/agent-lsp-*'` |

Host LSPs (`pyright-langserver`, …) are **not** used in production. Local mode
needs `AGENT_LSP_ALLOW_LOCAL=1` + `prefer_container=false` (tests/dev only).

## 1. Clone & sync

```bash
git clone https://github.com/hewimetall/agent-lsp-real-inspect.git
cd agent-lsp-real-inspect
uv sync --extra dev
make develop          # maturin develop for TaskStore + state/git/docker
```

Verify:

```bash
uv run python -c "from agent_lsp.server import mcp; print(mcp.name)"
# → agent-lsp
```

## 2. Build LSP images (required)

```bash
make docker-lsp
# versioned tags (ADR-0010):
make -C infra/docker/lsp versions
docker images 'ghcr.io/hewimetall/agent-lsp-*'
```

Nested / restricted hosts may need Docker `vfs` storage — see
`infra/docker/lsp/README.md`.

## 3. Data dirs

```bash
export AGENT_LSP_STATE="${AGENT_LSP_STATE:-$PWD/.data/state}"
export AGENT_LSP_PROJECTS="${AGENT_LSP_PROJECTS:-$PWD/.data/projects}"
export AGENT_LSP_WORKSPACES="${AGENT_LSP_WORKSPACES:-$PWD/.data/workspaces}"
export AGENT_LSP_CACHE="${AGENT_LSP_CACHE:-$PWD/.data/cache}"
mkdir -p "$AGENT_LSP_STATE" "$AGENT_LSP_PROJECTS" "$AGENT_LSP_WORKSPACES" "$AGENT_LSP_CACHE"
```

## 4. Start MCP server (stdio)

```bash
uv run agent-lsp
# or: uv run python -m agent_lsp.server
```

Point your MCP client at this stdio process. Long tools **require** `task=True`
([guide/tasks.md](tasks.md)).

## 5. Happy path (client)

```text
create_session
→ import_project(source=<git url|local path>, task=True)
→ checkout_workspace
→ ensure_runtime(language, language_version=…, prefer_container=…, task=True)
→ install_apt_packages([...], task=True)                 # optional
→ install_workspace_deps(language=…, packages=[…], task=True)
→ warm_index(task=True)
→ blast_radius / explore_symbol / find_references
→ close_session
```

Built-in smoke (imports **vmcp** as a Rust project under scout):

```bash
# local LSP (no Docker)
VMCP_SOURCE=/path/to/vmcp \
  uv run python scripts/client_vmcp_onboard.py
```

Deps-focused unit checks:

```bash
uv run pytest tests/test_deps_and_versions.py tests/test_tasks.py -q
```

## 6. Verify checklist

Run `./scripts/verify_runbook.sh solo` or manually:

- [ ] `uv run python -c "from agent_lsp.server import mcp"`
- [ ] `uv run pytest tests/test_deps_and_versions.py -q`
- [ ] `scripts/client_vmcp_onboard.py` exits 0 (local rust-analyzer)
- [ ] (optional) `docker images` shows `agent-lsp-python` / `agent-lsp-rust`
- [ ] After onboard: `index_status=ready`, scout tools return symbols

## See also

- [workspace-deps.md](workspace-deps.md) — deps / apt / versions
- [workspace-deps-validation.md](workspace-deps-validation.md) — frozen validation report
- [runbook-with-vmcp.md](runbook-with-vmcp.md) — same stack behind vmcp GraphQL
