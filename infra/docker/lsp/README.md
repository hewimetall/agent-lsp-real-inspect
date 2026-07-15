# LSP runtime images for agent-lsp

Images expose an LSP on **TCP `:3737`**. Session containers mount the active
worktree at `/workspace` (see ADR-0007 / `runtime_hub.ensure_container`).

| Language | Image | Server | Transport |
|----------|-------|--------|-----------|
| **go** | `ghcr.io/hewimetall/agent-lsp-go` | `gopls` | native `-listen=:3737` |
| **python** | `ghcr.io/hewimetall/agent-lsp-python` | `pyright-langserver` | stdio → [`common/stdio_tcp_bridge.py`](common/stdio_tcp_bridge.py) |
| **typescript** | `ghcr.io/hewimetall/agent-lsp-typescript` | `typescript-language-server` | stdio → bridge |
| **rust** | `ghcr.io/hewimetall/agent-lsp-rust` | `rust-analyzer` | stdio → bridge |
| **cpp** (c / c++) | `ghcr.io/hewimetall/agent-lsp-cpp` | `clangd` | stdio → bridge |

These match `agent_lsp.runtimes.RUNTIMES` (`c`, `c++`, `cxx`, `cc` normalize to `cpp`).

## Layout

```text
infra/docker/lsp/
  common/stdio_tcp_bridge.py   # TCP :3737 ↔ child stdio
  go/Dockerfile
  python/Dockerfile
  typescript/Dockerfile
  rust/Dockerfile
  cpp/Dockerfile
  Makefile
  build.sh
```

## Build

From this directory (build context must be `infra/docker/lsp` so `COPY common/...` works):

```bash
./build.sh                 # all languages
./build.sh go rust cpp     # subset
make all                   # same via Makefile
make python TAG=dev
```

Push:

```bash
make push TAG=latest
# or
REGISTRY=ghcr.io/hewimetall TAG=latest ./build.sh
docker push ghcr.io/hewimetall/agent-lsp-go:latest
```

## Contract with agent-lsp

1. Workdir inside the container: `/workspace` (bind-mounted worktree).
2. LSP accepts JSON-RPC on **TCP port 3737**.
3. `bollard` sets `Cmd` from `LanguageRuntime.cmd`:
   - **go** — full `gopls serve -listen=...` (no ENTRYPOINT).
   - **python / typescript / rust / cpp** — image `ENTRYPOINT` is the bridge; `Cmd` is the stdio language server.

### C/C++ (`clangd`)

Place or generate `compile_commands.json` in the worktree (or `build/`). Ceph and
similar CMake trees need this for accurate indexing; without it clangd still
starts but resolution is limited.

## Smoke (manual)

```bash
docker run --rm -p 127.0.0.1:3737:3737 -v "$PWD:/workspace" \
  ghcr.io/hewimetall/agent-lsp-go:latest
# then: agent-lsp ensure_runtime(session, "go") with prefer_container=true
```
