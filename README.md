<p align="center">
  <img src="assets/social-preview.png" alt="agent-lsp" width="600">
</p>

<p align="center">
  <a href="#tools"><img src="https://img.shields.io/badge/CI--verified_tools-65%2F65-brightgreen.svg" alt="CI Coverage"></a>
  <a href="#multi-language-support"><img src="https://img.shields.io/badge/languages-30_CI--verified-brightgreen.svg" alt="Languages"></a>
  <a href="https://github.com/blackwell-systems/mcp-assert"><img src="https://raw.githubusercontent.com/blackwell-systems/mcp-assert/main/assets/badge-passing.svg?v=3" alt="mcp-assert: passing" height="20"></a>
  <a href="https://agentskills.io"><img src="assets/badge-agentskills.svg" alt="Agent Skills"></a>
  <a href="https://github.com/blackwell-systems/agent-lsp"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/blackwell-systems/agent-lsp/main/assets/downloads-badge.json" alt="downloads"></a>
  <br>
  <a href="https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/"><img src="https://img.shields.io/badge/LSP-3.17-blue.svg" alt="LSP 3.17"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="https://github.com/punkpeye/awesome-mcp-servers"><img src="https://img.shields.io/badge/Awesome-MCP%20Servers-fc60a8" alt="Awesome MCP Servers"></a>
  <a href="https://github.com/blackwell-systems"><img src="https://raw.githubusercontent.com/blackwell-systems/blackwell-docs-theme/main/badge-trademark.svg" alt="Blackwell Systems"></a>
</p>

**Code intelligence infrastructure for AI agents.** 65 tools, 30 CI-verified languages, 24 agent workflows. Single Go binary.

## Quick start

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/blackwell-systems/agent-lsp/main/install.sh | sh

# Configure (auto-detects language servers, writes MCP config for your AI tool)
agent-lsp init
```

That's it. `agent-lsp init` detects your language servers, asks which AI tool you use (Claude Code, Cursor, Windsurf, Gemini CLI, Continue, Cline, or generic MCP), and writes the correct config. Your agent can now call any of the 65 tools.

<details>
<summary>Other install methods</summary>

```bash
brew install blackwell-systems/tap/agent-lsp     # macOS / Linux
pip install agent-lsp                             # pip
npm install -g @blackwell-systems/agent-lsp       # npm
go install github.com/blackwell-systems/agent-lsp/cmd/agent-lsp@latest  # Go
winget install BlackwellSystems.agent-lsp         # Windows
```

</details>

## What is it?

agent-lsp is an [MCP server](https://modelcontextprotocol.io/) that orchestrates existing language servers (gopls, rust-analyzer, jdtls, pyright, etc.) into agent-native workflows.

**Not an LSP server.** It's an orchestration layer: language servers provide code intelligence, agent-lsp batches and sequences their operations, AI agents consume the results via MCP.

## Why agent-lsp?

**Persistent warm runtime.** Language servers stay indexed across sessions. First call indexes the workspace (~10s). Every call after that is instant.

**Batch operations.** `blast_radius` returns all exports + all callers (test vs non-test partitioned) in one call. Without orchestration: 20+ sequential LSP calls.

**Speculative editing.** `simulate_edit` previews changes in memory, checks the diagnostic delta, applies or discards. Test edits before touching disk. 8 speculative execution tools. See [docs/guide/speculative-execution.md](./docs/guide/speculative-execution.md).

**Workflow orchestration.** 24 skills chain LSP operations into complete pipelines:
- `/lsp-refactor` → impact analysis → preview → apply → verify build → run tests
- `/lsp-safe-edit` → preview → diagnostic diff → apply if safe
- `/lsp-verify` → LSP diagnostics → build → test suite

**Multi-language, single session.** One process routes `.go` to gopls, `.ts` to tsserver, `.py` to pyright. No reconfiguration between projects.

## Token-optimized output

Tool responses are encoded in [GCF (Graph Compact Format)](https://gcformat.com) instead of JSON. GCF eliminates field-name repetition and structural overhead that make JSON expensive at scale.

| Profile | Savings vs JSON | When |
|---------|----------------|------|
| Tabular (all tools) | 30-51% | Every tool response |
| Graph (symbol-returning tools) | 79-84% | blast_radius, find_callers, explore_symbol, find_references, etc. |
| Graph + session dedup | 92.7% | 5th tool call in a session (via [gcf-proxy](https://github.com/blackwell-systems/gcf-proxy)) |

GCF is enabled by default. Set `AGENT_LSP_OUTPUT_FORMAT=json` to revert.

**GCF:** [gcformat.com](https://gcformat.com) · [Spec](https://github.com/blackwell-systems/gcf) · [Go](https://github.com/blackwell-systems/gcf-go) · [Python](https://github.com/blackwell-systems/gcf-python) · [TypeScript](https://github.com/blackwell-systems/gcf-typescript) · [Playground](https://gcformat.com/playground.html)

## Skills

Skills encode correct tool sequences so workflows complete without per-prompt orchestration. Available as MCP prompts (`prompts/list` / `prompts/get`) for any MCP client, and as slash commands in Claude Code.

**Before you change anything**

| Skill | Purpose |
|-------|---------|
| `/lsp-impact` | Blast-radius analysis before touching a symbol or file |
| `/lsp-implement` | Find all concrete implementations of an interface |
| `/lsp-dead-code` | Detect zero-reference exports before cleanup |

**Editing safely**

| Skill | Purpose |
|-------|---------|
| `/lsp-safe-edit` | Speculative preview before disk write; before/after diagnostic diff |
| `/lsp-simulate` | Test changes in-memory without touching the file |
| `/lsp-edit-symbol` | Edit a named symbol without knowing its file or position |
| `/lsp-edit-export` | Safe editing of exported symbols, finds all callers first |
| `/lsp-rename` | Preview all sites, confirm, apply atomically |

**Understanding unfamiliar code**

| Skill | Purpose |
|-------|---------|
| `/lsp-explore` | Hover + implementations + call hierarchy + references in one pass |
| `/lsp-understand` | Deep-dive Code Map: type info, call hierarchy, references, source |
| `/lsp-docs` | Three-tier documentation: hover, offline toolchain, source |
| `/lsp-cross-repo` | Find all usages of a library symbol across consumer repos |

**After editing**

| Skill | Purpose |
|-------|---------|
| `/lsp-verify` | Diagnostics + build + tests after every edit |
| `/lsp-fix-all` | Apply quick-fix code actions for all diagnostics in a file |
| `/lsp-test-correlation` | Find and run only tests that cover an edited file |

**Full workflow**

| Skill | Purpose |
|-------|---------|
| `/lsp-refactor` | End-to-end: blast-radius → preview → apply → verify → test |
| `/lsp-inspect` | Code quality audit (12 checks): dead symbols, coverage, error handling, concurrency |
| `/lsp-concurrency-audit` | Field-level concurrency safety audit for a type |

See [docs/guide/skills.md](./docs/guide/skills.md) for full descriptions. See [docs/guide/common-workflows.md](./docs/guide/common-workflows.md) for "I want to..." mapped to tools.

## Works with

| AI Tool | Transport | Setup |
|---------|-----------|-------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | stdio | `agent-lsp init` → writes `.mcp.json` |
| [Cursor](https://cursor.com) | stdio | `agent-lsp init` → writes `.cursor/mcp.json` |
| [Windsurf](https://windsurf.com) | stdio | `agent-lsp init` → writes config |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | stdio | `agent-lsp init` → writes `GEMINI.md` |
| [Continue](https://continue.dev) | stdio | `agent-lsp init` → writes `config.json` |
| [Cline](https://github.com/cline/cline) | stdio | `agent-lsp init` → writes settings |
| Any MCP client | HTTP+SSE | `agent-lsp --http --port 8080` with bearer token auth |

See [docs/getting-started/mcp-clients.md](./docs/getting-started/mcp-clients.md) for copy-paste configs.

## Docker

```bash
# Go
docker run --rm -i -v /your/project:/workspace ghcr.io/blackwell-systems/agent-lsp:go go:gopls

# TypeScript
docker run --rm -i -v /your/project:/workspace ghcr.io/blackwell-systems/agent-lsp:typescript typescript:typescript-language-server,--stdio

# Python
docker run --rm -i -v /your/project:/workspace ghcr.io/blackwell-systems/agent-lsp:python python:pyright-langserver,--stdio

# HTTP mode (persistent service)
docker run --rm -p 8080:8080 -v /your/project:/workspace \
  -e AGENT_LSP_TOKEN=your-secret-token \
  ghcr.io/blackwell-systems/agent-lsp:go --http --port 8080 go:gopls
```

Images run as non-root (uid 65532). Also mirrored to Docker Hub (`blackwellsystems/agent-lsp`). See [DOCKER.md](./DOCKER.md) for the full tag list and security hardening.

## Multi-language support

30 languages, CI-verified end-to-end against real language servers on every push. No other MCP-LSP implementation tests a single language in CI.

Go, Python, TypeScript, Rust, Java, C, C++, C#, Ruby, PHP, Kotlin, Swift, Scala, Zig, Lua, Elixir, Gleam, Clojure, Dart, Terraform, Nix, Prisma, SQL, MongoDB, JavaScript, YAML, JSON, Dockerfile, CSS, HTML.

See [docs/reference/language-support.md](./docs/reference/language-support.md) for the full coverage matrix with install commands.

## Tools

65 tools covering navigation, analysis, refactoring, symbol editing, speculative execution, and session lifecycle. All CI-verified. See [docs/reference/tools.md](./docs/reference/tools.md) for the full reference.

## Documentation

- [Getting started](./docs/getting-started/): installation, quickstart, MCP client configs, troubleshooting
- [Guides](./docs/guide/): skills, common workflows, speculative execution, GCF integration, phase enforcement
- [Reference](./docs/reference/): tools, language support, environment variables, LSP conformance
- [Architecture](./docs/architecture/): system design, CI, distribution, roadmap

## Development

```bash
git clone https://github.com/blackwell-systems/agent-lsp.git
cd agent-lsp && go build ./...
go test ./...                   # unit tests
go test ./... -tags integration # integration tests (requires language servers)
```

## License

MIT
