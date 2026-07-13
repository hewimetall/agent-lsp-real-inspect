# ADR-0007: Sessions hold containers

- Status: Accepted
- Date: 2026-07-13
- Code: D4

## Decision

Session binds long-lived LSP containers (bollard `start_persistent`).

State columns: `containers(container_id, session_id, image, language, host_port, …)`.

Fallback: local LSP subprocess when Docker unavailable (tests / bare metal),
всё равно пишется в session state (`runtime_mode=local`).
