# ADR-0010: Workspace deps, language versions, and apt bootstrap

- Status: Accepted
- Date: 2026-07-14
- Code: D7
- Deciders: product / architecture

## Context

Clients need more than “clone + attach LSP on a fixed `:latest` image”:

1. Pin a **language version** (Python 3.11 vs 3.14, Go 1.22/1.23, Node 20/22).
2. **Install project dependencies** so blast/refs resolve into `site-packages`,
   `GOMODCACHE`, or `node_modules`.
3. Optionally install **apt packages without an allowlist** so native build deps
   (headers, compilers) exist for the install step.
4. Reuse the existing gix clone/import → worktree → LSP pipeline (ADR-0006/0007).

Today `ensure_runtime` picks a single image tag and never runs package managers.
Pyright/gopls/tsserver therefore cannot see third-party symbols unless the tree
already vendors them.

## Decision

1. **`ensure_runtime(language, language_version="", image="")`** selects the LSP
   image (explicit `image` wins; else version tag map; else `:latest`) and records
   the version on the session runtime.

2. **Workspace-local env layout** under `.agent-lsp/` (and language caches under
   `AGENT_LSP_CACHE`):
   - python: `.agent-lsp/venv` (+ pyright `pythonPath` / `extraPaths` → site-packages)
   - typescript/js: worktree `node_modules`
   - go: `GOMODCACHE` / `GOPATH` bind mounts (ADR-0009)

3. **New task-required tools** (ADR-0001):
   - `install_workspace_deps` — auto or explicit manager (`pip`/`uv`/`npm`/`pnpm`/`go`);
     optional `packages[]` for ad-hoc deps; optional `apt_packages[]` in the **same**
     one-shot container before the language install.
   - `install_apt_packages` — no package allowlist; shell-quoted names only; persists
     the list in `.agent-lsp/apt-packages.txt` for later install runs.

4. Installs use **`DockerService.run`** (throwaway) with a **versioned base image**
   (`python:3.11-bookworm`, `golang:1.23`, `node:22`, …). The session-held LSP
   container (ADR-0007) is restarted after deps so the index sees new packages.

5. Git clone remains **`import_project` → `checkout_workspace` → deps →
   `ensure_runtime` → `warm_index` → scout**.

## Consequences

### Positive

- Clients can pin interpreters and get third-party resolution for blast/LSP.
- Apt bootstrap stays flexible (build headers) without inventing a package policy.
- Fits existing task worker + bollard split (one-shot install vs persistent LSP).

### Negative / risks

- Apt in a one-shot container does **not** persist into the LSP image; it only
  helps the install/build step unless the same packages are reapplied or baked in.
- Multi-version image matrix increases build/publish surface.
- Unvalidated apt names can fail at runtime (by design) or pull large packages.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Bake all deps into LSP images | Slow rebuilds; cannot match arbitrary projects |
| Host-only pip/npm without containers | Breaks hermetic version pins in cloud agents |
| Strict apt allowlist | Conflicts with “no validation, just build” |
| Mutate persistent LSP container with apt | Diverges from immutable image + ADR-0007 lifecycle |

## External validation

Cross-check vs Dev Containers / Pyright / gopls / tsserver / SCIP and related GitHub
issues (vmcp GraphQL aliased batch):
[`docs/guide/workspace-deps-validation.md`](../guide/workspace-deps-validation.md).
