# Architecture overview — scout rewrite

```text
                 ┌──────────────────────────────┐
                 │     FastMCP (Python)         │
                 │     agent-lsp core           │
                 │  sessions · scout tools      │
                 │  warm_index pipeline         │
                 └──────────────┬───────────────┘
        ┌───────────────────────┼────────────────────────┐
        ▼                       ▼                        ▼
┌───────────────┐      ┌───────────────┐       ┌────────────────┐
│ agent-lsp-state│      │ agent-lsp-git │       │ agent-lsp-docker│
│ sessions +     │      │ GitPort/gix   │       │ bollard         │
│ containers     │      │ bare+worktree │       │ long-lived LSP  │
│ (rusqlite)     │      │ clone/import  │       │ containers      │
└───────────────┘      └───────────────┘       └────────────────┘
```

## What we kept from agent-lsp

- LSP orchestration for agents
- **`blast_radius`** (signature tool)
- Scout skills: impact / explore / onboard / refactor / safe-edit / verify

## What we took from mcp-presentation

- FastMCP + Rust/PyO3 packages
- Sessions + workspaces (SQLite)
- Git bare + **worktree** (real sources, no CLI)
- Docker via **bollard** (no CLI) — containers **held by sessions**

## What we threw away

- Go monolith (66 low-level tools, daemon broker, GCF, phase engine)
- npm / winget / goreleaser Go distribution
- Speculative simulation session stack (can return later as a skill)

## Happy path

```text
create_session
  → import_project(project_id, url_or_path)   # real sources → bare
  → checkout_workspace(session_id, project_id) # gix worktree
  → ensure_runtime(session_id, language)       # container (or local fallback)
  → warm_index(session_id)                     # isolated index + cache warm
  → blast_radius / explore_symbol / …
  → close_session                              # stop containers
```

## Index pipeline

`warm_index` is isolated per session:

1. Runtime already bound (container or local)
2. Wait for LSP `$/progress` end (best-effort)
3. Seed `documentSymbol` + one `references` probe (cache warm)
4. Persist `index_status=ready` in state
