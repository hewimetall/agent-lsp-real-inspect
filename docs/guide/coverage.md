# Coverage

Rust and Python are **separate**. Gate uses **median**, not mean. Threshold: **93%**.

```bash
make cov-py    # scripts/python-coverage.sh  (median of per-file %)
make cov-rust  # scripts/rust-coverage.sh    (median of per-crate %)
make cov       # both
```

Env overrides:

| Var | Default |
|-----|---------|
| `PY_COV_FAIL_UNDER` | `93` |
| `RUST_COV_FAIL_UNDER` | `93` |

Mean is printed for diagnostics only. See [ADR-0008](../adr/0008-coverage-median-split.md).
