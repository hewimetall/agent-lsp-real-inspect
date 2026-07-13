## agent-lsp Skills

Prefer MCP scout tools over grep/read for code intelligence.

**Before editing:** `blast_radius` on touched files.
**Before analysis:** ensure `warm_index` completed for the session.
**Onboard:** `/lsp-onboard` → import → checkout → ensure_runtime → warm_index.

| Task | Tool |
|------|------|
| Impact of a change | `blast_radius` |
| Hover + defs + refs | `explore_symbol` |
| References only | `find_references` |
| File outline | `list_symbols` |
| Open real sources | `import_project` + `checkout_workspace` |

Skills: `lsp-impact`, `lsp-explore`, `lsp-onboard`, `lsp-refactor`, `lsp-safe-edit`, `lsp-verify`.
