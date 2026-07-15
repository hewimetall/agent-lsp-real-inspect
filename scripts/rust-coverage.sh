#!/usr/bin/env bash
# Rust coverage gate: MEDIAN of per-crate line % must be ≥ FAIL_UNDER.
# Separate from Python coverage (scripts/python-coverage.sh).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAIL_UNDER="${RUST_COV_FAIL_UNDER:-93}"
PY="${PYO3_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
export PYO3_PYTHON="$PY"

# Help linker find libpython when -dev package is missing.
export LIBRARY_PATH="${ROOT}/.libs:${LIBRARY_PATH:-}"
export LD_LIBRARY_PATH="${ROOT}/.libs:${LD_LIBRARY_PATH:-}"
PY_LIB="$("$PY" -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR") or "")')"
if [[ -n "$PY_LIB" ]]; then
  export LD_LIBRARY_PATH="$PY_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  export LIBRARY_PATH="$PY_LIB${LIBRARY_PATH:+:$LIBRARY_PATH}"
fi

CRATES=(
  "$ROOT|agent-lsp-core"
  "$ROOT/packages/agent-lsp-state|agent-lsp-state"
  "$ROOT/packages/agent-lsp-git|agent-lsp-git"
  "$ROOT/packages/agent-lsp-docker|agent-lsp-docker"
  "$ROOT/packages/agent-lsp-runtime-worker|agent-lsp-runtime-worker"
)

if ! command -v cargo-llvm-cov >/dev/null 2>&1; then
  echo "cargo-llvm-cov not found; install: cargo install cargo-llvm-cov && rustup component add llvm-tools-preview" >&2
  exit 1
fi

echo "==> rust coverage (median of crates ≥ ${FAIL_UNDER}%)"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
pct_file="$tmpdir/pcts.txt"
: >"$pct_file"
status=0

for entry in "${CRATES[@]}"; do
  crate="${entry%%|*}"
  name="${entry##*|}"
  echo "==> rust coverage: $name"
  lcov_out="$tmpdir/$name.lcov"
  # Binary crates: measure the library only (main.rs is thin glue + Docker I/O).
  extra_args=()
  if [[ "$name" == "agent-lsp-runtime-worker" ]]; then
    extra_args=(--lib)
  fi
  if ! (
    cd "$crate"
    cargo llvm-cov --no-default-features "${extra_args[@]}" --lcov --output-path "$lcov_out"
  ); then
    echo "FAIL: cargo llvm-cov failed for $name" >&2
    status=1
    continue
  fi
  (cd "$crate" && cargo llvm-cov report --summary-only "${extra_args[@]}") || true
  python3 - "$lcov_out" "$name" "$pct_file" <<'PY'
import sys
from pathlib import Path
lcov = Path(sys.argv[1])
name = sys.argv[2]
out = Path(sys.argv[3])
total = hit = 0
for line in lcov.read_text().splitlines():
    if line.startswith("DA:"):
        _n, counts = line[3:].split(",", 1)
        total += 1
        if counts != "0":
            hit += 1
pct = 100.0 if total == 0 else (100.0 * hit / total)
print(f"{name}: {hit}/{total} lines = {pct:.2f}%")
out.write_text(out.read_text() + f"{pct}\n")
PY
done

python3 - "$FAIL_UNDER" "$pct_file" <<'PY'
import statistics
import sys
from pathlib import Path
fail = float(sys.argv[1])
lines = [ln.strip() for ln in Path(sys.argv[2]).read_text().splitlines() if ln.strip()]
if not lines:
    print("FAIL: no rust crate coverage numbers", file=sys.stderr)
    sys.exit(1)
pcts = [float(x) for x in lines]
median = statistics.median(pcts)
mean = statistics.fmean(pcts)
print(f"rust crates={len(pcts)} median={median:.2f}% mean={mean:.2f}% (gate=median)")
if median + 1e-9 < fail:
    print(f"FAIL: rust median coverage {median:.2f}% < {fail:.0f}%", file=sys.stderr)
    sys.exit(1)
print(f"OK: rust median {median:.2f}% ≥ {fail:.0f}%")
PY
exit_code=$?
if [[ $status -ne 0 ]]; then
  exit 1
fi
exit "$exit_code"
