---
name: lsp-impact
description: Blast-radius analysis for a symbol or file before editing.
---

# lsp-impact

Chat fields (not MCP `/prompts`):
[`infra/requests/impact.template.md`](../../infra/requests/impact.template.md).

1. Ensure session has workspace + `ensure_runtime`/`warm_index` (**`task=True`**).
2. Call `blast_radius` with `changed_files`.
3. Report non-test vs test callers; halt if blast is unexpectedly large.
