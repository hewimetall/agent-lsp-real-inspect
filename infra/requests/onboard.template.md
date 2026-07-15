# onboard — fill in chat (not /prompt)

```text
project_id: <id>
source: <git-url | local-path | mirror:<id>>
ref_name: <HEAD | branch>
language: <python|go|typescript|rust>
language_version: <e.g. 3.12>
packages: <optional pip/npm/go pkgs>
apt_packages: <optional>
ensure_runtime: <yes|no>
warm_index: <yes|no>
notes: <optional>
```

Example:

```text
project_id: dramatiq
source: https://github.com/Bogdanp/dramatiq.git
ref_name: HEAD
language: python
language_version: 3.12
packages: redis
apt_packages:
ensure_runtime: yes
warm_index: yes
notes: blast on dramatiq/actor.py
```

Agent: `skills/lsp-onboard/SKILL.md`
