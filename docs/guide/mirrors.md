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

## Fail-closed rules

| Source | Behavior |
|--------|----------|
| `mirror:ceph` (synced) | `import_local` from `AGENT_LSP_MIRRORS/ceph.git` |
| `mirror:ceph` (missing bare) | error — run `mirror-sync.py sync ceph` |
| `mirror:` / `mirror://` (empty id) | error — never treated as a git URL |
| `mirror:cngp` with empty `url=` | error — fill TOML first |
| `https://…` / local path | unchanged (pre-existing); mirrors are operational, not an egress allowlist |

Symlink escapes out of `AGENT_LSP_MIRRORS` are rejected after `resolve()`.

## Chat request fields (not MCP /prompts)

Important templates (from agent-lsp skills): [`infra/requests/README.md`](../../infra/requests/README.md).

Mirror fields: [`infra/requests/mirror.template.md`](../../infra/requests/mirror.template.md).

Do **not** register or serve these via FastMCP `@mcp.prompt` / Cursor Prompt UI.

Agent steps: [`skills/lsp-mirror/SKILL.md`](../../skills/lsp-mirror/SKILL.md).

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
