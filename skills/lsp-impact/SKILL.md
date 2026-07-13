---
name: lsp-impact
description: Blast-radius analysis for a symbol or file before editing.
---

# /lsp-impact

1. Ensure session has workspace + `ensure_runtime` + `warm_index`.
2. Call `blast_radius` with `changed_files`.
3. Report non-test vs test callers; halt if blast is unexpectedly large.
