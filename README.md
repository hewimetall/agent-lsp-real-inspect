# agent-lsp-real-inspect-mcp

MCP server that gives coding agents a **warm LSP index** — so they can inspect symbols and check **blast radius** before editing code.

## Try it (30 seconds)

```bash
uvx agent-lsp-real-inspect-mcp --version
uvx agent-lsp-real-inspect-mcp --help
```

You should see the package version and a short CLI help. That means the PyPI install works.

To start the MCP server (stdio — it will sit waiting for a client):

```bash
uvx agent-lsp-real-inspect-mcp
```

| Name | What it is |
|------|------------|
| **`agent-lsp-real-inspect-mcp`** | PyPI package + `uvx` command (use this) |
| `agent-lsp` | Short console script alias after install |
| [blackwell-systems/agent-lsp](https://github.com/blackwell-systems/agent-lsp) | **Different** project (Go). Owns the PyPI name `agent-lsp`. |

## Cursor setup

1. Add to MCP config (`~/.cursor/mcp.json` or project `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "agent-lsp": {
      "command": "uvx",
      "args": ["agent-lsp-real-inspect-mcp"],
      "env": {
        "FASTMCP_SHOW_CLI_BANNER": "false"
      }
    }
  }
}
```

2. Restart MCP / reload Cursor.
3. Confirm the server shows tools such as `create_session`, `warm_index`, `blast_radius`.
4. Ask the agent something like: *“Create a scout session and import this repo.”*

Pin a version: `"args": ["agent-lsp-real-inspect-mcp==0.1.7"]`.

## Requirements

| Need | When |
|------|------|
| Python ≥ 3.12 + [`uv`](https://docs.astral.sh/uv/) | always (`uvx`) |
| **Docker** | only for real scout work (`ensure_runtime` / `warm_index` / deps). Not needed for `--help` / `--version`. |

Languages: **Go · Python · TypeScript · Rust · C/C++**

## What you get

Compared to grep/read loops:

| Tool | Job |
|------|-----|
| `blast_radius` | What else breaks / depends on this change |
| `explore_symbol` | Hover + defs + refs in one call |
| `warm_index` | Index once; later calls reuse the warm runtime |
| `find_references` / `go_to_definition` / `list_symbols` | Standard LSP ops for agents |

Long setup tools (`import_project`, `ensure_runtime`, `warm_index`, …) must be called with **`task=True`**. See [`docs/guide/tasks.md`](docs/guide/tasks.md).

## Typical flow

```text
create_session
  → import_project(source=<git|path>, task=True)
  → checkout_workspace
  → ensure_runtime(language=…, task=True)
  → install_workspace_deps(…, task=True)   # optional
  → warm_index(task=True)
  → blast_radius / explore_symbol / …
  → close_session
```

Step-by-step: [`docs/guide/runbook-solo.md`](docs/guide/runbook-solo.md).

## Use it when

- Impact analysis before a refactor (`blast_radius`)
- Symbol navigation where grep is too noisy (`explore_symbol`)
- Many agent turns that should reuse one warm index

## Docs

| Doc | When |
|-----|------|
| [`docs/guide/runbook-solo.md`](docs/guide/runbook-solo.md) | Run alone |
| [`docs/guide/runbook-with-vmcp.md`](docs/guide/runbook-with-vmcp.md) | Behind vmcp |
| [`docs/guide/tasks.md`](docs/guide/tasks.md) | Why `task=True` |
| [`docs/guide/workspace-deps.md`](docs/guide/workspace-deps.md) | Install deps in the runtime |
| [`docs/`](docs/) | Full index |

## Install as a tool

```bash
uv tool install agent-lsp-real-inspect-mcp
agent-lsp-real-inspect-mcp --help
# short alias:
agent-lsp --help
```

## Development

```bash
git clone https://github.com/hewimetall/agent-lsp-real-inspect.git
cd agent-lsp-real-inspect
uv sync --extra dev
make develop
uv run agent-lsp      # local stdio MCP
pytest -q
```

LSP images (needed for real scout runs):

```bash
make docker-lsp
```

See [`infra/docker/lsp/README.md`](infra/docker/lsp/README.md).  
Release notes: [`docs/guide/pypi-release.md`](docs/guide/pypi-release.md).

## License

MIT — see [`LICENSE`](LICENSE).
