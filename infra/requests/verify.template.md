# verify — fill in chat (not /prompt)

After edits: re-warm if needed, re-blast, spot-check symbols.

```text
session_id: <uuid or current>
touched_files: <path1, path2, …>
rewarm: <yes|no>
spot_check: <file:line:col, …>
notes: <optional>
```

Example:

```text
session_id: current
touched_files: python/agent_lsp/mirrors.py, python/agent_lsp/worker.py
rewarm: no
spot_check: python/agent_lsp/mirrors.py:140:5
notes: after fail-closed fix
```

Agent: `skills/lsp-verify/SKILL.md`
