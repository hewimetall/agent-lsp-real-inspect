---
name: lsp-explore
description: Scout a symbol — hover, definition, references in one pass.
---

# lsp-explore

Chat fields (not MCP `/prompts`):
[`infra/requests/explore.template.md`](../../infra/requests/explore.template.md).

1. `explore_symbol(session_id, file_path, line, column)`
2. Optionally follow with `blast_radius` on the containing file.
