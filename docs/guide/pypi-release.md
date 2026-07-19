# PyPI release (by tag)

Publish manylinux / macOS / Windows wheels on every `v*` tag via
[`.github/workflows/release.yml`](../../.github/workflows/release.yml).

## Install / run with uv

```bash
uvx agent-lsp-real-inspect-mcp --help
uvx agent-lsp-real-inspect-mcp --version
# no args → MCP stdio server
uvx agent-lsp-real-inspect-mcp
# or install as a tool
uv tool install agent-lsp-real-inspect-mcp
agent-lsp --help   # same entrypoint
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
4. Smoke-imports the linux **manylinux** wheels only
5. Publishes with **Trusted Publishing** (`uv publish`, env `pypi`) — main first, then siblings
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

### 2. PyPI Trusted Publishers (pending) — REQUIRED for all four

For **each** project below, PyPI → Publishing → **Add a new pending publisher**.
The **PyPI project** column must match wheel `Name:` metadata **exactly**
(hyphens, not underscores).

| PyPI project | Owner | Repository | Workflow | Environment |
|--------------|-------|------------|----------|-------------|
| `agent-lsp-state` | `hewimetall` | `agent-lsp-real-inspect` | `release.yml` | `pypi` |
| `agent-lsp-git` | `hewimetall` | `agent-lsp-real-inspect` | `release.yml` | `pypi` |
| `agent-lsp-docker` | `hewimetall` | `agent-lsp-real-inspect` | `release.yml` | `pypi` |
| `agent-lsp-real-inspect-mcp` | `hewimetall` | `agent-lsp-real-inspect` | `release.yml` | `pypi` |

Publisher provider: **GitHub**.

The first successful upload for a pending publisher creates that PyPI project.

#### Current gate (v0.1.6)

Verified 2026-07-19 after Release run
[29691916098](https://github.com/hewimetall/agent-lsp-real-inspect/actions/runs/29691916098):

| Check | Result |
|-------|--------|
| Build matrix (16 jobs) | green |
| Smoke (manylinux pick) | green (`smoke_ok`) |
| `uv publish` | **FAILED** on first sibling |
| PyPI JSON for all four | still 404 (no files) |
| Empty project `agent-lsp-real-inspect-mcp` | **exists** (`/simple/` 200, no files) |

Error:

```text
400 Non-user identities cannot create new projects. This was probably caused by
successfully using a pending publisher but specifying the project name incorrectly
```

Interpretation (PyPI docs): a pending publisher for
`agent-lsp-real-inspect-mcp` fired while uploading `agent-lsp-state` first →
empty main project created, upload rejected (metadata name mismatch).

**Human action before next tag / re-run:**

1. Confirm Trusted Publisher is attached on existing empty project
   `agent-lsp-real-inspect-mcp` (pending was consumed when the project was created).
2. Add **pending** publishers for the three siblings with exact names:
   `agent-lsp-state`, `agent-lsp-git`, `agent-lsp-docker`
   (same owner/repo/workflow=`release.yml`/env=`pypi`).
3. Do **not** retag until those three pending publishers exist.
4. After publishers are ready: retag `v0.1.6` (still unpublished files) or bump.

Do **not** ship only the main package: it depends on the three siblings.

## CI failure notes (v0.1.6)

| Stage | Symptom | Fix |
|-------|---------|-----|
| Windows build | `UnicodeEncodeError` on `→` in stamp script | ASCII `->` + `PYTHONUTF8=1` |
| Linux build | separate `maturin sdist` step: `sccache … No such file` | build sdist via `--sdist` in the same wheel step |
| Publish smoke | `ls *.whl \| head -1` picked `macosx_arm64` on Linux runner | select `*manylinux*.whl` only |
| `uv publish` | pending publisher name ≠ wheel `Name:` (siblings missing) | four matching publishers; publish main first |

### Checklist before tagging

- [ ] `cargo test` / `pytest` green on `main`
- [ ] Version bump decided (semver) — if prior tag never published files, same `vX.Y.Z` may be retagged
- [ ] Trusted Publisher ready for **all four** names above (env `pypi`, workflow `release.yml`)
- [ ] GitHub Environment `pypi` exists
- [ ] Tag annotated: `git tag -a vX.Y.Z -m "…"` + `git push origin vX.Y.Z`
- [ ] Watch Actions → Release: build green → smoke manylinux → `uv publish` all four → Release assets
- [ ] Confirm: `curl -sI https://pypi.org/pypi/<each-of-four>/json` → 200
- [ ] Confirm: `uvx agent-lsp-real-inspect-mcp --help` prints usage (does not hang on stdio)
- [ ] Confirm: `uvx agent-lsp-real-inspect-mcp --version` prints the stamped version
