## agent-lsp Skills

Prefer MCP scout tools over grep/read for code intelligence.

**Long tools require `task=True`:** `import_project`, `ensure_runtime`, `warm_index`.
**Before editing:** `blast_radius` on touched files.
**Before analysis:** `warm_index` completed for the session.
**Onboard:** MCP prompt `onboard` or `/lsp-onboard` → import → checkout → ensure_runtime → warm_index.
**Prompts:** MCP `prompts/list` → `onboard`, `mirror`, `explore`, `impact`, `safe_edit`, `verify`
(`python/agent_lsp/prompts.py`).

| Task | Tool |
|------|------|
| Impact of a change | `blast_radius` |
| Hover + defs + refs | `explore_symbol` |
| Open real sources | `import_project` + `checkout_workspace` |
| Inspect scout task | `get_task_status` |
| Guided flows | MCP prompts (`onboard`, `explore`, …) |

ADL/ADR: `docs/adr/`. Coverage: median ≥93% separately for Python and Rust (`make cov`).
