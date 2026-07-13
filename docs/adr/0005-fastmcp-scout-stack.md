# ADR-0005: FastMCP scout stack

- Status: Accepted
- Date: 2026-07-13
- Code: D2
- Supersedes: Go agent-lsp monolith

## Decision

| Package | Role |
|---------|------|
| `agent-lsp` | FastMCP + TaskStore + scout tools |
| `agent-lsp-state` | sessions / workspaces / containers |
| `agent-lsp-git` | gix bare + worktree |
| `agent-lsp-docker` | bollard long-lived containers |

Keep: LSP orchestration, `blast_radius`, scout skills.  
Drop: Go binary, GCF, phase engine, 66 low-level tools, npm/winget.
