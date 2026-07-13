# ADR-0006: Git via gix worktrees

- Status: Accepted
- Date: 2026-07-13
- Code: D3

## Decision

`agent-lsp-git` (GitPort → GixGitAdapter):

- `init_bare` / `clone_bare` / `import_local`
- `add_worktree` / `commit`
- **no git CLI, no push**

Реальные исходники материализуются в `workspaces/<id>/`.
