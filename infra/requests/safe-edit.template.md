# safe-edit — fill in chat (not /prompt)

Blast first, then edit worktree only if callers look safe.

```text
session_id: <uuid or current>
file_path: <file to edit>
intent: <what to change>
run_blast: <yes|no>
commit: <yes|no>
commit_message: <optional>
notes: <optional>
```

Example:

```text
session_id: current
file_path: python/agent_lsp/mirrors.py
intent: reject empty mirror: prefix
run_blast: yes
commit: no
notes: keep fail-closed
```

Agent: `skills/lsp-safe-edit/SKILL.md`
