# Client flow: versioned workspace + deps + LSP/blast

Happy path for Python (same idea for Go / JS·TS):

```text
create_session
import_project(source=<git url|local path>)   # task=True
checkout_workspace
ensure_runtime(language=python, language_version=3.11)   # task=True
install_apt_packages(packages=[build-essential, …])      # task=True, no allowlist
install_workspace_deps(packages=[dramatiq, redis], apt_packages=[…])  # task=True
warm_index   # task=True
blast_radius / find_references / explore_symbol
```

## What gets installed where

| Language | Deps location | How LSP sees them |
|----------|---------------|-------------------|
| Python | `.agent-lsp/venv` (+ `lib/pythonX.Y/site-packages`) | pyright `pythonPath` + `extraPaths` |
| TypeScript / JS | `node_modules/` | tsserver project resolution |
| Go | `go.mod` + `GOMODCACHE` under `AGENT_LSP_CACHE` | gopls env |

## Apt packages

- **No allowlist / validation** — names are shell-quoted only.
- Persisted in `.agent-lsp/apt-packages.txt`.
- Applied inside the **throwaway install container** (same run as pip/npm/go) so native build deps exist while compiling wheels / cgo / node-gyp.
- They do **not** permanently mutate the session-held LSP image (ADR-0007 / ADR-0010).

## Adding more deps later (hot-swap)

Call `install_workspace_deps` again with more `packages`. By default
(`restart_runtime=true`) the session LSP is **force-recycled**
(`ensure_container(..., force=True)` / `ensure_local(..., force=True)`) so
site-packages / node_modules are reloaded without leaving the session cold —
replacement starts first; the previous runtime is torn down only after the new
LSP is reachable. Then call `warm_index` again.

If recycle fails, the previous runtime is kept with `needs_recycle=True` (index
`cold`); the next `ensure_runtime` must start a fresh LSP. With
`restart_runtime=false`, settings are refreshed in-place; a dead TCP transport
(Broken pipe) is marked `stale` instead of a silent no-op.

## Version pins

`language_version` selects:

1. Install base image (`python:3.11-bookworm`, `golang:1.23-bookworm`, `node:22-bookworm`)
2. LSP image tag when published (`ghcr.io/hewimetall/agent-lsp-python:3.11`, …)

Override with `image=` / `install_image=` when needed.

See ADR-0010 and `skills/lsp-onboard/SKILL.md`.

Validation vs similar systems/issues: [`workspace-deps-validation.md`](workspace-deps-validation.md)
(**Accepted / frozen**).

Raise the stack:

- Solo: [`runbook-solo.md`](runbook-solo.md)
- With vmcp: [`runbook-with-vmcp.md`](runbook-with-vmcp.md)
- Check: `./scripts/verify_runbook.sh solo|with-vmcp`
