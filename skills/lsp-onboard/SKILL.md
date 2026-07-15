---
name: lsp-onboard
description: Open real sources into a warm scout session (task=True required).
---

# /lsp-onboard

1. `create_session`
2. `import_project(project_id, source)` with **`task=True`**
   - `source` = git URL, local path, **or** `mirror:<id>` (from
     [`infra/mirrors/mirrors.toml`](../../infra/mirrors/mirrors.toml);
     sync first: `uv run python scripts/mirror-sync.py sync <id>`)
3. `checkout_workspace(session_id, project_id)`
4. Optional bootstrap:
   - `install_apt_packages(session_id, packages=[...])` **`task=True`** — no allowlist
   - `install_workspace_deps(session_id, language=..., language_version=..., packages=[...], apt_packages=[...])` **`task=True`**
     - Python → `.agent-lsp/venv` (site-packages visible to pyright)
     - JS/TS → `node_modules`
     - Go → module cache under `AGENT_LSP_CACHE`
5. `ensure_runtime(session_id, language, language_version="3.11")` with **`task=True`**
6. `warm_index(session_id)` with **`task=True`**
7. Scout: `blast_radius`, `explore_symbol`, `find_references`, …

See `docs/guide/tasks.md` and ADR-0010.
