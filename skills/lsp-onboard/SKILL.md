---
name: lsp-onboard
description: Open real sources into a warm scout session (task=True required).
---

# /lsp-onboard

1. `create_session`
2. `import_project(project_id, source)` with **`task=True`**
3. `checkout_workspace(session_id, project_id)`
4. `ensure_runtime(session_id, language)` with **`task=True`**
5. `warm_index(session_id)` with **`task=True`**
6. Ready for scout tools (`blast_radius`, `explore_symbol`, …)

See `docs/guide/tasks.md`.
