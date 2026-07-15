# explore — fill in chat (not /prompt)

Requires warm session (`index_status=ready`).

```text
session_id: <uuid or current>
file_path: <path under workspace>
line: <1-based>
column: <1-based>
follow_blast: <yes|no>
notes: <optional>
```

Example:

```text
session_id: current
file_path: src/pybind/mgr/dashboard/module.py
line: 42
column: 10
follow_blast: yes
notes: Module class
```

Agent: `skills/lsp-explore/SKILL.md` → `explore_symbol` (+ optional `blast_radius`)
