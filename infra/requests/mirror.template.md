# mirror — fill in chat (not /prompt)

```text
mirror_ids: <ceph, minio, …>
sync_now: <yes|no>
language: <python|go|typescript|rust|cpp>
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

Catalog: `infra/mirrors/mirrors.toml` · Agent: `skills/lsp-mirror/SKILL.md`
