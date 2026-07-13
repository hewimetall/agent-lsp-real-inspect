# ADR-0008: Coverage — median ≥93%, Rust ≠ Python

- Status: Accepted
- Date: 2026-07-13
- Code: D5

## Context

Среднее (mean) маскирует «дыры»: один большой хорошо покрытый файл тянет mean вверх,
пока половина модулей на нуле. Нужен жёсткий, честный gate.

## Decision

1. **Rust и Python — раздельные coverage** (отдельные скрипты / артефакты / CI steps).
2. Gate = **медиана** per-unit line coverage, **не среднее**.
3. Порог: **≥ 93%** (`PY_COV_FAIL_UNDER` / `RUST_COV_FAIL_UNDER`).

| Suite | Unit | Script |
|-------|------|--------|
| Python | per-file `%` → median | `scripts/python-coverage.sh` |
| Rust | per-crate `%` → median | `scripts/rust-coverage.sh` |

Mean печатается для диагностики, но **не** используется в gate.

## Consequences

- Чтобы пройти gate, большинство файлов/crates должны быть хорошо покрыты.
- Нельзя «дотянуть» mean одним огромным happy-path тестом.
