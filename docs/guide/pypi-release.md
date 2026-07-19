# PyPI release (by tag)

Publish **one** manylinux / macOS / Windows wheel on every `v*` tag via
[`.github/workflows/release.yml`](../../.github/workflows/release.yml).

Native `StateStore` / `GitService` / `DockerService` ship inside the same wheel
(Python import names `agent_lsp_state` / `agent_lsp_git` / `agent_lsp_docker`
are kept as thin wrappers).

## Install / run with uv

```bash
uvx agent-lsp-real-inspect-mcp --help
uvx agent-lsp-real-inspect-mcp --version
# no args → MCP stdio server
uvx agent-lsp-real-inspect-mcp
uv tool install agent-lsp-real-inspect-mcp
agent-lsp --help   # same entrypoint
```

> PyPI name is **`agent-lsp-real-inspect-mcp`**. Upstream already owns
> [`agent-lsp`](https://pypi.org/project/agent-lsp/) (Go monolith).

> **`v0.1.6` is broken** on PyPI: it declared missing sibling deps. Use
> **`>=0.1.7`**. Prefer yanking `0.1.6` on PyPI.

## Cut a release

```bash
git checkout main && git pull
git tag -a v0.1.7 -m v0.1.7
git push origin v0.1.7
```

The workflow:

1. Stamps version + renames dist to `agent-lsp-real-inspect-mcp`
2. Builds **one** package (maturin) for linux / macOS intel / macOS arm / Windows (+ sdist on Linux)
3. Smoke-imports the linux **manylinux** wheel (compat imports included)
4. Publishes with **Trusted Publishing** (`uv publish`, env `pypi`)
5. Attaches artifacts to the GitHub Release

## One-time GitHub + PyPI setup

### 1. GitHub Environment

Repo → **Settings → Environments → New environment** → name `pypi`.

### 2. PyPI Trusted Publisher — **one** project

PyPI → Publishing → **Add a new pending publisher** (or confirm on existing project):

| Field | Value |
|-------|-------|
| PyPI project | `agent-lsp-real-inspect-mcp` |
| Owner | `hewimetall` |
| Repository | `agent-lsp-real-inspect` |
| Workflow | `release.yml` |
| Environment | `pypi` |

No Trusted Publishers needed for `agent-lsp-state` / `git` / `docker`.

### Checklist before tagging

- [ ] `cargo test` / `pytest` green on `main`
- [ ] Version bump decided (semver) — next after broken `0.1.6` is `0.1.7`
- [ ] Trusted Publisher ready for `agent-lsp-real-inspect-mcp` only
- [ ] Tag annotated + pushed
- [ ] Release green → `curl -sI https://pypi.org/pypi/agent-lsp-real-inspect-mcp/json` → 200
- [ ] `uvx agent-lsp-real-inspect-mcp==0.1.7 --help` prints usage
- [ ] Optional: yank `0.1.6` on PyPI (depends on missing siblings)
