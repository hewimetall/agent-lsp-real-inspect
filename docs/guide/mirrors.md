# Local git mirrors (manual sync)

Heavy / build-from-source trees are **not** cloned by `import_project`.
Operators pull them into a local mirror dir from a TOML catalog, then roll
workspaces out with `source="mirror:<id>"`.

## Catalog

[`infra/mirrors/mirrors.toml`](../../infra/mirrors/mirrors.toml) — list of
`[[mirror]]` entries (`id`, `url`, `ref`, `depth`, `kind`, `tags`, `notes`).

Default entries: `ceph`, `cngp` (url empty — fill in), `minio`, `cpython`,
`postgres`, plus python-build libs (`cryptography`, `psycopg`, `numpy`).

## Env

| Var | Purpose | Default |
|-----|---------|---------|
| `AGENT_LSP_MIRRORS` | Bare clones root (`<id>.git`) | sibling of projects, or `./mirrors` |
| `AGENT_LSP_MIRRORS_TOML` | Path to catalog | `infra/mirrors/mirrors.toml` |

Production bootstrap sets both under `/var/lib/agent-lsp` + `/opt/agent-lsp`.

## Sync (always by hand)

```bash
# on the host that runs agent-lsp
export AGENT_LSP_MIRRORS=/var/lib/agent-lsp/mirrors
export AGENT_LSP_MIRRORS_TOML=/opt/agent-lsp/infra/mirrors/mirrors.toml

uv run python scripts/mirror-sync.py list
uv run python scripts/mirror-sync.py sync ceph minio cpython postgres
uv run python scripts/mirror-sync.py sync --tag python-build
# re-clone one:
uv run python scripts/mirror-sync.py sync ceph --force
```

Uses **git CLI** (shallow `--depth` or `--mirror`). Scout import still uses
gix (`import_local` from the bare path) — no network at MCP time.

## Onboard from mirror

```text
create_session
import_project(project_id="ceph", source="mirror:ceph")   # or mirror://ceph
checkout_workspace(session_id, "ceph")
ensure_runtime(...) / warm_index(...)
```

If the bare is missing: error tells you to run `mirror-sync.py sync <id>`.
If `url` is empty in TOML (e.g. `cngp`): fill `url=` then sync.

## Add a mirror

1. Edit `infra/mirrors/mirrors.toml` — add `[[mirror]]` with `id` + `url`.
2. `mirror-sync.py sync <id>`
3. `import_project(..., source="mirror:<id>")`

See ADR-0011.
