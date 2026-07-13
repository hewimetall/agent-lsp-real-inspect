# ADR-0001: FastMCP + Rust/PyO3 rewrite

- Status: Accepted
- Date: 2026-07-13

## Context

agent-lsp was a large Go MCP binary. We want the same scout value
(`blast_radius`, LSP, skills) with the simpler stack proven in
[mcp-presentation](https://github.com/hewimetall/mcp-presentation):
FastMCP orchestration + small PyO3 packages.

## Decision

Rewrite as a Python FastMCP server with three native packages:

| Package | Role |
|---------|------|
| `agent-lsp-state` | sessions, workspaces, container bindings (rusqlite) |
| `agent-lsp-git` | bare + worktree + clone/import (gix, no CLI) |
| `agent-lsp-docker` | long-lived session containers (bollard, no CLI) |

Sessions hold containers. Index/warm runs as an explicit pipeline tool.

## Consequences

- Much smaller surface; scout tools only
- Real source checkouts via worktrees
- Local LSP fallback when Docker is absent (tests / bare metal)
