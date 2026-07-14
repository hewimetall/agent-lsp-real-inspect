# Validation: workspace deps + versioned runtimes (via vmcp/mcpwork)

Sources gathered in **two aliased `query_graphql` batches** (Tavily, Context7,
Searchcode, SerpApi) against ADR-0010 / `install_workspace_deps` /
`ensure_runtime(language_version=…)`.

## Verdict

**ADR-0010 matches established industry patterns.** Closest analogues:

| Pattern | Similar system | Our mapping |
|---------|----------------|-------------|
| Pin interpreter / toolchain version | [Dev Container Features](https://devcontainers.github.io/implementors/features) `options.version` (python/node/go) | `ensure_runtime(language_version=…)` + install base images |
| Install deps into workspace before analysis | [scip-python](https://sourcegraph.com/blog/scip-python) — index from an activated venv with deps installed | `install_workspace_deps` → `.agent-lsp/venv` / `node_modules` / `GOMODCACHE` |
| Point LSP at env, not only source tree | Pyright `venvPath`/`venv`/`pythonPath`/`extraPaths` ([docs](https://github.com/microsoft/pyright/blob/main/docs/configuration.md)) | `lsp_settings.build_lsp_settings` → `workspace/configuration` |
| Apt / build headers only for compile | Multi-stage Docker: `apt-get` in builder, wheels into volume | `apt_packages` in **same throwaway** install container; list in `.agent-lsp/apt-packages.txt` |
| Session-held LSP + durable caches | gopls `GOMODCACHE` / `GOPLSCACHE` ([golang/tools](https://github.com/golang/tools)) | ADR-0009 binds under `AGENT_LSP_CACHE` |

**Not a novel invention** — it is Dev Containers (version + apt + install) composed with
pyright/gopls/tsserver resolution rules and Sourcegraph’s “index with deps present” rule.

## Supporting docs (Context7)

- **Pyright** (`/microsoft/pyright`): `venvPath`/`venv` steer import resolution into the
  venv’s `site-packages`; prefer `pythonPath` / `--pythonpath` when the interpreter is known.
- **gopls** (`/websites/go_dev_gopls`): per-project env (`GOPATH`, PATH) is a supported
  editor pattern; module cache is env-driven (`GOMODCACHE`).
- **typescript-language-server**: resolves via workspace `node_modules` / TS project;
  init options include `npmLocation`, `maxTsServerMemory`.

## Recurring issues our design already addresses

### 1. Host `processId` inside Docker → LSP exits

- Spec: `processId` may be `null`; if set and parent is gone, server should exit
  ([LSP 3.17](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/)).
- Real bugs: [anomalyco/opencode#36162](https://github.com/anomalyco/opencode/issues/36162)
  (explicit fix: rewrite `processId` → `null` for container LSPs);
  [denoland/deno#22012](https://github.com/denoland/deno/issues/22012).
- **Ours:** TCP/container clients send `processId: null` (`LspClient.initialize`).

### 2. Pyright missing venv / site-packages

- [microsoft/pyright#702](https://github.com/microsoft/pyright/issues/702) — cannot find
  virtualenv packages without correct config.
- [microsoft/pyright#4839](https://github.com/microsoft/pyright/issues/4839) — Docker +
  `venvPath`/`site-packages` layout surprises (`lib/site-packages` vs `lib/pythonX.Y/...`).
- **Ours:** create `.agent-lsp/venv`, discover `lib/python*/site-packages`, push
  `pythonPath` + `extraPaths` over LSP configuration.

### 3. Go module / gopls cache in constrained environments

- vscode-go / go issues around module cache paths and install failures when `GOMODCACHE`
  is wrong (e.g. [golang/vscode-go#2573](https://github.com/golang/vscode-go/issues/2573)).
- **Ours:** bind `AGENT_LSP_CACHE/gomod/<session>` → `/go/pkg/mod` + `GOPLSCACHE`.

### 4. Apt does not persist in ephemeral containers

- Standard Docker practice: apt only in the **build/install** stage; runtime image stays
  slim (wheel-builder blogs, cgo/Docker writeups).
- **Ours (documented trade-off in ADR-0010):** apt runs in throwaway install container and
  is reapplied on later `install_workspace_deps` via persisted list — **not** baked into
  the session-held LSP image (ADR-0007).

### 5. Version pinning as a first-class option

- Dev Containers Features expose `version` enums for Python/Node/Go and run `install.sh`
  (often with apt) — see `devcontainers/features` python/node/go feature definitions.
- **Ours:** `language_version` → install image (`python:3.11-bookworm`, …) and LSP tag map.

## Gaps / residual risks (from research)

| Risk | Evidence | Mitigation status |
|------|----------|-------------------|
| Pyright `venvPath` alone flaky; prefer `pythonPath` | Sublime/LSP-pyright threads; pyright docs | We set both `pythonPath` and `extraPaths` |
| Multi-version LSP image matrix must be published | Devcontainer images are versioned on Hub | `infra/docker/lsp/Makefile` `versions` target; fallback tag |
| tsserver needs install **before** warm | Docker/Node guides; tsserver project load | Onboard skill orders deps → ensure → warm |
| Apt-only without later deps install is a no-op for LSP | Ephemeral container semantics | Docs warn; list persisted for next install |
| SCIP indexers still need deps present | Sourcegraph scip-python blog | Same invariant as blast/refs |

## What we did **not** copy (and why)

| Alternative | Why not for agent-lsp |
|-------------|------------------------|
| Full Dev Container lifecycle per session | Heavier than bollard one-shot install + persistent LSP (ADR-0007) |
| Bake all deps into LSP images | Breaks arbitrary projects; slow rebuilds (ADR-0010 alternatives) |
| Host-only pip without versioned containers | Loses hermetic `language_version` |

## GraphQL batching note

Validation used **vmcp `query_graphql` only**, with many **top-level aliases** per
document (Tavily × N, Context7 resolve/queryDocs, Searchcode, SerpApi) — not sequential
per-upstream tool calls. `tavily_research` hit a plan rate limit (432); coverage came from
aliased `tavily_search` + extracts + Context7 + Searchcode instead.
