# Runbook: поднять agent-lsp **вместе с vmcp**

agent-lsp становится **stdio upstream** в [vmcp](https://github.com/hewimetall/vmcp).
Клиент (Cursor / cloud agent / curl) ходит в **один** endpoint vmcp
(`query_graphql` + aliases), а не в agent-lsp напрямую.

Examples in-repo: [`infra/vmcp/`](../../infra/vmcp/).

## Architecture

```text
MCP client ──HTTP/stdio──► vmcp (:8765/mcp)
                              │  registry.json
                              ▼
                         agent-lsp (stdio child)
                              │  prefer_container?
                              ▼
                    LSP containers :3737  (Docker-only; local needs AGENT_LSP_ALLOW_LOCAL=1)
```

## 0. Prerequisites

All of [runbook-solo.md](runbook-solo.md) **plus**:

| Need | Check |
|------|-------|
| vmcp source or binary | `git clone https://github.com/hewimetall/vmcp.git` |
| Rust **stable ≥ 1.85** (edition2024 deps) | `rustup default stable` · `rustc --version` |

**Verified in CI-like lab (2026-07-14):** `cargo build -p vmcp --release` on rustc 1.97,
registry → `uv run agent-lsp`, `curl :8765/health → ok`, upstream `agent-lsp` spawned,
`native MCP tasks enabled … tools=5`, `./scripts/verify_runbook.sh with-vmcp` → 13/13 PASS.

## 1. Prepare agent-lsp (solo steps 1–3)

```bash
cd /path/to/agent-lsp-real-inspect
uv sync --extra dev && make develop
export AGENT_LSP_HOME="$PWD"
export AGENT_LSP_STATE="$PWD/.data/state"
export AGENT_LSP_PROJECTS="$PWD/.data/projects"
export AGENT_LSP_WORKSPACES="$PWD/.data/workspaces"
export AGENT_LSP_CACHE="$PWD/.data/cache"
mkdir -p "$AGENT_LSP_STATE" "$AGENT_LSP_PROJECTS" "$AGENT_LSP_WORKSPACES" "$AGENT_LSP_CACHE"
```

Confirm:

```bash
uv run --directory "$AGENT_LSP_HOME" agent-lsp --help >/dev/null || \
  uv run --directory "$AGENT_LSP_HOME" python -c "from agent_lsp.server import main; print('ok')"
```

(`agent-lsp` entrypoint = `agent_lsp.server:main`, stdio MCP.)

## 2. Clone / build vmcp

```bash
git clone https://github.com/hewimetall/vmcp.git /path/to/vmcp
cd /path/to/vmcp
```

Copy the example registry + sidecar from agent-lsp:

```bash
mkdir -p ./demo/agent-lsp
cp /path/to/agent-lsp-real-inspect/infra/vmcp/registry.agent-lsp.json ./demo/agent-lsp/registry.json
cp /path/to/agent-lsp-real-inspect/infra/vmcp/specs/agent-lsp.json ./demo/specs/agent-lsp.json
```

Edit `demo/agent-lsp/registry.json`:

- set `command` / `cwd` to your agent-lsp checkout + `uv` path
- set `env.AGENT_LSP_*` data dirs
- keep `"name": "agent-lsp"` (GraphQL namespace → `agentLsp` / `AgentLspRead|Write`)

## 3. Enable tasks on vmcp (recommended)

Long agent-lsp tools use FastMCP `TaskConfig(mode="optional")` (Cursor uses
progress; task-capable clients may still pass `task=True`). Behind vmcp:

- **GraphQL sync** (`query_graphql`) awaits the upstream call — only works if the
  gateway invokes the tool in a way FastMCP accepts as a task, **or**
- **Preferred:** enable native MCP Tasks and mark tools in the sidecar
  (`task_support: required`) so clients use `run_task`.

In `vmcp.toml` (or env):

```toml
[tasks]
enabled = true
db_path = "state/tasks.db"
task_ttl_ms = 600000
poll_interval_ms = 1000
max_concurrent = 8

[auth]
# local only:
# enabled = false
```

Env equivalent:

```bash
export VMCP_TASKS__ENABLED=true
export VMCP_AUTH__ENABLED=false   # local dev only
```

Sidecar (`infra/vmcp/specs/agent-lsp.json`) marks:

`import_project`, `ensure_runtime`, `warm_index`, `install_workspace_deps`,
`install_apt_packages` → `task_support: required`.

## 4. Start vmcp with agent-lsp upstream

```bash
cd /path/to/vmcp
export VMCP_REGISTRY_PATH=./demo/agent-lsp/registry.json
export VMCP_SPEC_DIR=./demo/specs
export VMCP_AUTH__ENABLED=false
export VMCP_TASKS__ENABLED=true
export VMCP_UPSTREAM__SPAWN_TIMEOUT_MS=120000

cargo run -p vmcp
# → http://127.0.0.1:8765
```

Verify:

```bash
curl -fsS http://127.0.0.1:8765/health
# → ok
```

## 5. Client via GraphQL aliases (one document)

Discovery + tool list in **one** aliased call:

```graphql
query {
  servers { name description toolCount }
  search_scout: search(q: "blast warm import") {
    server tool readOnly description
  }
  agentLspType: __type(name: "AgentLspWrite") {
    fields { name }
  }
}
```

Onboard sketch (names follow vmcp camelCase of MCP tools — confirm via `__type`):

```graphql
# Prefer run_task for task-required tools when [tasks] enabled.
# Exact field names: inspect AgentLspWrite after boot.
```

Cursor: point MCP URL at `http://127.0.0.1:8765/mcp` (OAuth if auth enabled;
default demo password `demo-master`). See vmcp [`docs/clients.md`](https://github.com/hewimetall/vmcp/blob/main/docs/clients.md).

**Always batch independent reads with GraphQL aliases** — never N sequential
`query_graphql` round-trips for related questions.

## 6. Alternative: smoke without GraphQL

You can still validate agent-lsp alone while vmcp is for aggregation of *other*
upstreams:

```bash
VMCP_SOURCE=/path/to/vmcp uv run python scripts/client_vmcp_onboard.py
```

This script uses in-process FastMCP `Client(mcp)` — it does **not** need the
vmcp gateway. Use it to prove scout works; use §4–5 to prove gateway wiring.

## 7. Verify checklist

`./scripts/verify_runbook.sh with-vmcp` (agent-lsp side) plus:

- [ ] `curl /health` → `ok`
- [ ] GraphQL `{ servers { name } }` lists `agent-lsp`
- [ ] `{ search(q: "blast") { server tool } }` finds scout tools
- [ ] Sidecar / `tools.lock.json` shows `taskSupport` for long tools
- [ ] End-to-end: import → ensure → warm → blast via gateway client

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Upstream spawn timeout | Raise `VMCP_UPSTREAM__SPAWN_TIMEOUT_MS`; ensure `uv run agent-lsp` works alone |
| Tools missing task support | Copy sidecar; enable `[tasks]`; restart vmcp |
| Docker LSP fails under nested env | `vfs` storage; load pre-built images; do not enable host local in prod |
| Auth / OAuth loops locally | `VMCP_AUTH__ENABLED=false` for lab only |

## See also

- [runbook-solo.md](runbook-solo.md)
- [workspace-deps-validation.md](workspace-deps-validation.md)
- vmcp: [deployment](https://github.com/hewimetall/vmcp/blob/main/docs/deployment.md), [tasks](https://github.com/hewimetall/vmcp/blob/main/docs/tasks.md), [aggregation workshop](https://github.com/hewimetall/vmcp/blob/main/docs/mcp-aggregation-workshop.md)
