# Mirror onboard — fill in chat (plain message, not /prompt)

Copy fields into an ordinary chat message. Do **not** use MCP `/prompts`
or Cursor Prompt UI — this is not an MCP prompt resource.

```text
mirror_ids: <ceph, minio, …>
sync_now: <yes|no>
language: <python|go|typescript|rust>
language_version: <e.g. 3.12>
ensure_runtime: <yes|no>
warm_index: <yes|no>
notes: <optional>
```

Example:

```text
mirror_ids: ceph
sync_now: yes
language: python
language_version: 3.12
ensure_runtime: yes
warm_index: yes
notes: explore src/pybind/mgr
```

Catalog: [`mirrors.toml`](mirrors.toml) · Agent steps: [`skills/lsp-mirror/SKILL.md`](../../skills/lsp-mirror/SKILL.md)
