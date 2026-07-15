# ADR-0012: Separate Rust runtime-health worker

- Status: Accepted
- Date: 2026-07-15
- Code: D4.1

## Context

Session-held LSP containers (ADR-0007) persist bindings in SQLite
(`containers.status=running`, `sessions.index_status=ready`). The MCP process
also keeps an in-memory `RuntimeHub` client. When Docker kills a container
(OOM, daemon restart, manual `docker rm`) without updating SQLite:

1. Hub reuses the dead TCP client → `Broken pipe` on scout tools.
2. `ensure_runtime` skips recreate because `existing.client` is still set.
3. Operators see `ready` in DB while clangd/pyright is gone.

Reconciling inside the FastMCP process couples health polling to request
latency and restarts. A small dedicated binary can own Docker inspect + SQLite
updates without PyO3.

## Decision

1. Ship **`agent-lsp-runtime-worker`** (`packages/agent-lsp-runtime-worker`):
   polls `$AGENT_LSP_STATE/sessions.db`, inspects each `status=running`
   container via bollard, and on dead/missing rows sets
   `containers.status=stopped` and `sessions.index_status=stale`
   (does not overwrite `closed`).
2. Skip `runtime_mode=local` / `local-*` ids (test escape hatch).
3. systemd unit `agent-lsp-runtime-worker.service`; interval via
   `AGENT_LSP_RUNTIME_WORKER_INTERVAL_SECS` (default 15).
4. Defense in depth in Python: `DockerService.is_running` before hub reuse;
   scout `_client_for` returns `runtime_stale` when the Engine says stopped.

## Consequences

- DB truth lags at most one poll interval; clients must re-call
  `ensure_runtime` + `warm_index` after `stale`.
- Worker needs Docker socket + write access to `sessions.db` (same as MCP).
- Coverage: crate is part of the Rust median gate (ADR-0008).
