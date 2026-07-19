# PyPI release (by tag)

Publish manylinux / macOS / Windows wheels on every `v*` tag via
[`.github/workflows/release.yml`](../../.github/workflows/release.yml).

## Install / run with uv

```bash
uvx agent-lsp-real-inspect-mcp
# or pin a version
uvx agent-lsp-real-inspect-mcp==0.1.6
# or install as a tool
uv tool install agent-lsp-real-inspect-mcp
agent-lsp   # same entrypoint
```

> PyPI name is **`agent-lsp-real-inspect-mcp`**. Upstream already owns
> [`agent-lsp`](https://pypi.org/project/agent-lsp/) (Go monolith).

## Cut a release

```bash
git checkout main && git pull
git tag -a v0.1.6 -m v0.1.6
git push origin v0.1.6
```

The workflow:

1. Stamps all package versions from the tag (`scripts/release-set-version.sh`)
2. Renames the main dist to `agent-lsp-real-inspect-mcp` and pins sibling deps
3. Builds wheels (maturin) for:
   - Linux x86_64 (`ubuntu-latest`, manylinux)
   - macOS **x86_64** (`macos-15-intel`)
   - macOS **aarch64** (`macos-latest`)
   - Windows x64 (`windows-latest`)
   - plus sdists on Linux
4. Smoke-imports the linux wheels
5. Publishes with **Trusted Publishing** (`uv publish`, env `pypi`)
6. Attaches artifacts to the GitHub Release

macOS runners match current `maturin generate-ci github` (Intel dedicated
runner + Apple Silicon) — not a single `macos-latest` that only covers one arch.

## One-time GitHub + PyPI setup

### 1. GitHub Environment

Repo → **Settings → Environments → New environment**

| Field | Value |
|-------|-------|
| Name | `pypi` |

Optional: require reviewers before the publish job runs.

### 2. PyPI Trusted Publishers (pending)

For **each** project below, PyPI → Publishing → **Add a new pending publisher**:

| PyPI project | Owner | Repository | Workflow | Environment |
|--------------|-------|------------|----------|-------------|
| `agent-lsp-state` | `hewimetall` | `agent-lsp-real-inspect` | `release.yml` | `pypi` |
| `agent-lsp-git` | `hewimetall` | `agent-lsp-real-inspect` | `release.yml` | `pypi` |
| `agent-lsp-docker` | `hewimetall` | `agent-lsp-real-inspect` | `release.yml` | `pypi` |
| `agent-lsp-real-inspect-mcp` | `hewimetall` | `agent-lsp-real-inspect` | `release.yml` | `pypi` |

Publisher provider: **GitHub**.

The first successful tag push creates the PyPI projects automatically.
