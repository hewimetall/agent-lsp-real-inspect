---
name: lsp-verify
description: After edits — re-warm if needed and re-check blast/diagnostics.
---

# lsp-verify

Chat fields (not MCP `/prompts`):
[`infra/requests/verify.template.md`](../../infra/requests/verify.template.md).

1. Confirm session `index_status` is `ready` (else `warm_index`).
2. `blast_radius` on touched files.
3. Spot-check `inspect_symbol` / `find_references` on critical symbols.
