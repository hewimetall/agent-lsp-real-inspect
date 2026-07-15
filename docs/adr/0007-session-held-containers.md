# ADR-0007: Sessions hold containers

- Status: Accepted
- Date: 2026-07-13
- Code: D4

## Decision

Session binds long-lived LSP containers (bollard `start_persistent`).

State columns: `containers(container_id, session_id, image, language, host_port, …)`.

Fallback: local LSP subprocess **only** when `AGENT_LSP_ALLOW_LOCAL=1` and
`prefer_container=false` (tests / bare-metal escape hatch). Production is
**Docker-only** — container start failures do not fall back to the host.
Session state still records `runtime_mode=local|container`.

After `install_workspace_deps` with `restart_runtime=true`, the hub recycles via
`ensure_container(..., force=True)` / `ensure_local(..., force=True)` so the LSP
reloads deps even when language/image are unchanged. Replacement starts first;
`put()` tears down the previous runtime only after the new LSP is reachable.
If recycle fails, the previous runtime is kept with `needs_recycle=True` so
`warm_index` errors and the next `ensure_runtime` must start a fresh LSP.
