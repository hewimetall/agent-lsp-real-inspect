# Chat request templates (from agent-lsp skills)

Plain markdown for ordinary chat messages.

**Not** MCP `/prompts`, **not** FastMCP `@mcp.prompt`, **not** Cursor Prompt UI.

| Template | When | Skill |
|----------|------|-------|
| [`onboard.template.md`](onboard.template.md) | open sources + warm LSP | `skills/lsp-onboard` |
| [`mirror.template.md`](mirror.template.md) | heavy tree from local mirror | `skills/lsp-mirror` |
| [`explore.template.md`](explore.template.md) | hover / defs / refs | `skills/lsp-explore` |
| [`impact.template.md`](impact.template.md) | blast before edit | `skills/lsp-impact` |
| [`safe-edit.template.md`](safe-edit.template.md) | edit with blast gate | `skills/lsp-safe-edit` |
| [`verify.template.md`](verify.template.md) | re-check after edits | `skills/lsp-verify` |

Skipped (composite / less often): `lsp-refactor` — use impact → explore → safe-edit → verify.

Catalog for mirrors: [`../mirrors/mirrors.toml`](../mirrors/mirrors.toml).
