# ADR-0011: Local git mirrors (TOML + manual sync)

- Status: Accepted
- Date: 2026-07-15
- Code: D8

## Context

Full clones of Ceph / CPython / Postgres (and similar) via `import_project`
time out or stall on small VDS hosts. Operators still need those trees in
scout workspaces.

## Decision

1. Catalog mirrors in **`infra/mirrors/mirrors.toml`** (`[[mirror]]` rows).
2. **Manual sync only** — `scripts/mirror-sync.py` (git CLI shallow/mirror)
   into `AGENT_LSP_MIRRORS`. Never auto-fetched by MCP / worker.
3. `import_project(source="mirror:<id>")` resolves to the local bare and
   `import_local` via gix (ADR-0006). Missing bare → clear error to sync.

## Consequences

- Disk / network cost is operator-controlled (`depth=1` default for large trees).
- `cngp` and other private URLs stay empty until filled in TOML.
- Deploy bootstrap creates `…/mirrors` and points `AGENT_LSP_MIRRORS(_TOML)`.
- Empty `mirror:` / `mirror://` fail closed (not passed to `clone_bare`).
- Direct git URL / local-path `import_project` remains available to bearer holders
  (mirrors are an operational optimization, not an egress policy).
- `paths.mirrors_dir()` and `mirrors.mirrors_root()` share one resolution rule;
  `mirror-sync.py` prefers the catalog next to the script’s repo checkout.
- Onboard fields live in `infra/mirrors/REQUEST.template.md` / skill `lsp-mirror`
  as ordinary chat text — **not** exposed via MCP `/prompts`.