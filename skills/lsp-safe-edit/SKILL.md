---
name: lsp-safe-edit
description: Preview impact before changing code.
---

# lsp-safe-edit

Chat fields (not MCP `/prompts`):
[`infra/requests/safe-edit.template.md`](../../infra/requests/safe-edit.template.md).

1. `blast_radius` on the file you will edit
2. If non-test callers look safe, edit in the active worktree
3. Re-run `explore_symbol` / `find_references` after the change
