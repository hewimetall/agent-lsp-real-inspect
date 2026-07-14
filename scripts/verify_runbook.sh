#!/usr/bin/env bash
# Verify runbook prerequisites / smoke for agent-lsp (solo or with-vmcp prep).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-solo}"
REPORT="${VERIFY_REPORT:-/opt/cursor/artifacts/verify-runbook-${MODE}.json}"
mkdir -p "$(dirname "$REPORT")"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cd "$ROOT"
: >"$TMP/results.jsonl"
pass=0
fail=0

check() {
  local name="$1"
  shift
  if "$@" >"$TMP/out" 2>"$TMP/err"; then
    echo "PASS  $name"
    printf '{"name":"%s","ok":true}\n' "$name" >>"$TMP/results.jsonl"
    pass=$((pass + 1))
  else
    echo "FAIL  $name"
    echo "      stderr: $(head -c 400 "$TMP/err" | tr '\n' ' ')"
    printf '{"name":"%s","ok":false}\n' "$name" >>"$TMP/results.jsonl"
    fail=$((fail + 1))
  fi
}

echo "== verify_runbook mode=$MODE root=$ROOT =="

check "uv_available" bash -lc 'command -v uv'
check "python_import_mcp" bash -lc "cd '$ROOT' && uv run python -c 'from agent_lsp.server import mcp; assert mcp.name==\"agent-lsp\"'"
check "unit_deps_versions" bash -lc "cd '$ROOT' && uv run pytest tests/test_deps_and_versions.py -q --tb=line"
check "unit_tasks_slice" bash -lc "cd '$ROOT' && uv run pytest tests/test_tasks.py::test_worker_install_deps_local tests/test_tasks.py::test_taskstore_submit_claim_done -q --tb=line"
check "infra_vmcp_registry" test -f "$ROOT/infra/vmcp/registry.agent-lsp.json"
check "infra_vmcp_sidecar" test -f "$ROOT/infra/vmcp/specs/agent-lsp.json"
check "docs_validation_frozen" grep -q "Accepted / frozen" "$ROOT/docs/guide/workspace-deps-validation.md"
check "docs_runbook_solo" test -f "$ROOT/docs/guide/runbook-solo.md"
check "docs_runbook_vmcp" test -f "$ROOT/docs/guide/runbook-with-vmcp.md"

if [[ "$MODE" == "solo" || "$MODE" == "with-vmcp" ]]; then
  if command -v rust-analyzer >/dev/null 2>&1; then
    SRC="${VMCP_SOURCE:-/tmp/client-srcs/vmcp}"
    if [[ -d "$SRC" ]]; then
      check "client_vmcp_onboard_local" bash -lc "cd '$ROOT' && VMCP_SOURCE='$SRC' uv run python scripts/client_vmcp_onboard.py"
    else
      echo "SKIP  client_vmcp_onboard_local (no VMCP_SOURCE at $SRC)"
    fi
  else
    echo "SKIP  client_vmcp_onboard_local (no rust-analyzer)"
  fi
fi

if [[ "$MODE" == "with-vmcp" ]]; then
  VMCP_ROOT="${VMCP_ROOT:-/tmp/client-srcs/vmcp}"
  check "vmcp_source_present" test -f "$VMCP_ROOT/Cargo.toml"
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    check "docker_daemon" true
  else
    echo "SKIP  docker_daemon"
  fi
  if curl -fsS http://127.0.0.1:8765/health >/dev/null 2>&1; then
    check "vmcp_health" curl -fsS http://127.0.0.1:8765/health
  else
    echo "SKIP  vmcp_health (gateway not running on :8765 — start per runbook-with-vmcp.md)"
  fi
fi

python3 - "$TMP/results.jsonl" "$REPORT" "$MODE" "$pass" "$fail" <<'PY'
import json, sys
path, report_path, mode, passed, failed = sys.argv[1:6]
rows = [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
doc = {
    "mode": mode,
    "pass": int(passed),
    "fail": int(failed),
    "ok": int(failed) == 0,
    "results": rows,
}
open(report_path, "w", encoding="utf-8").write(json.dumps(doc, indent=2) + "\n")
print(json.dumps({"mode": mode, "pass": int(passed), "fail": int(failed), "ok": int(failed) == 0}, indent=2))
print(f"REPORT → {report_path}")
PY

echo "== summary: pass=$pass fail=$fail =="
[[ "$fail" -eq 0 ]]
