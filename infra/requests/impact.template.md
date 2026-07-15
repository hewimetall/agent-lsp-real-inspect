# impact — fill in chat (not /prompt)

Requires warm session. Run before edits.

```text
session_id: <uuid or current>
changed_files: <path1, path2, …>
include_transitive: <yes|no>
halt_if_large: <yes|no>
notes: <optional>
```

Example:

```text
session_id: current
changed_files: python/agent_lsp/worker.py
include_transitive: no
halt_if_large: yes
notes: before restart_runtime change
```

Agent: `skills/lsp-impact/SKILL.md` → `blast_radius`
