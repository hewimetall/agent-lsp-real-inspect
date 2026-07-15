---
name: lsp-mirror
description: Sync local git mirrors by hand, then onboard a workspace from mirror:<id>.
---

# /lsp-mirror

Heavy trees live in [`infra/mirrors/mirrors.toml`](../../infra/mirrors/mirrors.toml).
**MCP never pulls them** — sync on the host, then `import_project(source="mirror:<id>")`.

## Chat prompt (copy / fill)

Paste into chat and fill the blanks:

```text
/lsp-mirror

mirror_ids: <ceph, minio, …>          # from mirrors.toml; comma-separated
sync_now: <yes|no>                    # yes → run mirror-sync.py on the host first
language: <python|go|typescript|rust>
language_version: <e.g. 3.12|1.23|22>
ensure_runtime: <yes|no>              # default yes
warm_index: <yes|no>                  # default yes
notes: <optional>
```

Example:

```text
/lsp-mirror

mirror_ids: ceph
sync_now: yes
language: python
language_version: 3.12
ensure_runtime: yes
warm_index: yes
notes: explore src/pybind/mgr
```

## Agent checklist

1. If `sync_now=yes` (or mirror bare missing): on the **agent-lsp host**
   ```bash
   export AGENT_LSP_MIRRORS=${AGENT_LSP_MIRRORS:-/var/lib/agent-lsp/mirrors}
   export AGENT_LSP_MIRRORS_TOML=${AGENT_LSP_MIRRORS_TOML:-/opt/agent-lsp/infra/mirrors/mirrors.toml}
   uv run python scripts/mirror-sync.py sync <ids…>
   ```
   Prefer running the script from the agent-lsp checkout (it loads
   `<repo>/infra/mirrors/mirrors.toml` next to the script).
   If `url` empty in TOML (e.g. `cngp`) — stop and ask for URL; do not invent one.
   Never use bare `mirror:` / `mirror://` as `source`.
2. `create_session`
3. For each id: `import_project(project_id=<id>, source="mirror:<id>")`
4. `checkout_workspace(session_id, project_id=<id>)` (first id if several)
5. If `ensure_runtime=yes`: `ensure_runtime(..., language=…, language_version=…)`
6. If `warm_index=yes`: `warm_index(session_id)`
7. Scout only after warm: `explore_symbol` / `blast_radius` / …

See [`docs/guide/mirrors.md`](../../docs/guide/mirrors.md) and ADR-0011.
