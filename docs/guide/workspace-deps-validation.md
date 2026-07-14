# Validation report (FIXED) — workspace deps + versioned runtimes

- **Status:** Accepted / frozen
- **Date:** 2026-07-14
- **Method:** vmcp/mcpwork `query_graphql` with **GraphQL aliases** (batched; not 1-by-1)
- **Scope:** ADR-0010 + `install_workspace_deps` / `install_apt_packages` / `language_version`
- **Companion runbooks:** [runbook-solo.md](runbook-solo.md) · [runbook-with-vmcp.md](runbook-with-vmcp.md)

## Verdict (locked)

**ADR-0010 matches established industry patterns.** It is Dev Containers (version +
apt + install) composed with pyright/gopls/tsserver resolution rules and
Sourcegraph’s “index only with deps present” rule — not a novel invention.

| Pattern | Similar system | agent-lsp mapping |
|---------|----------------|-------------------|
| Pin interpreter / toolchain | [Dev Container Features](https://devcontainers.github.io/implementors/features) `options.version` | `ensure_runtime(language_version=…)` + install base images |
| Install deps before analysis | [scip-python](https://sourcegraph.com/blog/scip-python) (venv with deps) | `install_workspace_deps` → `.agent-lsp/venv` / `node_modules` / `GOMODCACHE` |
| Point LSP at env | Pyright `venvPath` / `pythonPath` / `extraPaths` | `lsp_settings` → `workspace/configuration` |
| Apt only for compile | Multi-stage Docker wheel/cgo builders | `apt_packages` in throwaway install container + `.agent-lsp/apt-packages.txt` |
| Session LSP + durable caches | gopls `GOMODCACHE` / `GOPLSCACHE` | ADR-0009 binds under `AGENT_LSP_CACHE` |

## Evidence sources (batched)

Two aliased GraphQL documents covering:

- **Tavily** — web patterns + GitHub issue search
- **Context7** — `/microsoft/pyright`, `/websites/go_dev_gopls`, `/typescript-language-server/typescript-language-server`
- **Searchcode** — `microsoft/pyright`, `golang/tools`, `devcontainers/features`, `sourcegraph/scip-python`
- **SerpApi** — supplemental SERP (some queries empty / rate-limited)

`tavily_research` hit plan limit (HTTP 432); coverage remained via aliased search + extract.

## Issues our design already closes

| Issue | Link | Our fix |
|-------|------|---------|
| Host `processId` in Docker → LSP exits | [opencode#36162](https://github.com/anomalyco/opencode/issues/36162), [deno#22012](https://github.com/denoland/deno/issues/22012), [LSP 3.17](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/) | TCP clients send `processId: null` |
| Pyright missing venv packages | [pyright#702](https://github.com/microsoft/pyright/issues/702), [#4839](https://github.com/microsoft/pyright/issues/4839) | `.agent-lsp/venv` + `pythonPath`/`extraPaths` |
| Go module cache path failures | e.g. [vscode-go#2573](https://github.com/golang/vscode-go/issues/2573) | bind `GOMODCACHE` / `GOPLSCACHE` |
| Apt does not persist in ephemeral containers | Docker multi-stage practice | reapply from `.agent-lsp/apt-packages.txt` on deps install |

## Residual risks (accepted)

1. Multi-version LSP image tags must be published (`make -C infra/docker/lsp versions`).
2. Apt-only without a later deps install does not change what the LSP sees.
3. `tsserver` / pyright need deps **before** `warm_index` (skill order enforces this).

## Freeze note

This report is the canonical validation artifact for ADR-0010. Update only when
the architecture changes; re-run research with **one aliased `query_graphql`
document**, not sequential per-tool calls.
