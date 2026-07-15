#!/usr/bin/env python3
"""Remote FastMCP *client* smoke against a live agent-lsp (production).

Exercises the same path a real MCP client uses:
  create_session → import_project → checkout_workspace →
  ensure_runtime(task, container) → warm_index(task) →
  list_symbols / explore_symbol (when a seed file is found)

Default target: https://lsp.runmcp.ru/mcp

Usage:
  AGENT_LSP_BEARER_TOKEN=… uv run python scripts/client_prod_smoke.py
  AGENT_LSP_MCP_URL=https://lsp.runmcp.ru/mcp CLIENT_ONLY=cpp,go \\
    uv run python scripts/client_prod_smoke.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastmcp import Client

URL = os.environ.get("AGENT_LSP_MCP_URL", "https://lsp.runmcp.ru/mcp")
TOKEN = os.environ.get("AGENT_LSP_BEARER_TOKEN", "").strip()
ONLY = {
    x.strip().lower()
    for x in os.environ.get("CLIENT_ONLY", "").split(",")
    if x.strip()
}
REPORT_PATH = Path(
    os.environ.get(
        "CLIENT_REPORT",
        "/opt/cursor/artifacts/prod-client-smoke-report.json",
    )
)
WARM_TIMEOUT = float(os.environ.get("CLIENT_WARM_TIMEOUT", "180"))


@dataclass(frozen=True)
class Target:
    name: str
    project_id: str
    source: str
    language: str
    seed_globs: tuple[str, ...]


# Prefer mirrors already synced on prod; rust/ts use public GitHub.
TARGETS: tuple[Target, ...] = (
    Target(
        name="ceph-cpp",
        project_id="ceph",
        source="mirror:ceph",
        language="cpp",
        seed_globs=("src/common/*.cc", "src/common/*.h", "**/*.cc", "**/*.cpp"),
    ),
    Target(
        name="minio-go",
        project_id="minio",
        source="mirror:minio",
        language="go",
        seed_globs=("cmd/**/*.go", "**/*.go"),
    ),
    Target(
        name="cryptography-py",
        project_id="cryptography",
        source="mirror:cryptography",
        language="python",
        seed_globs=("src/cryptography/**/*.py", "**/*.py"),
    ),
    Target(
        name="vmcp-rust",
        project_id="vmcp-client-smoke",
        source=os.environ.get(
            "VMCP_SOURCE", "https://github.com/hewimetall/vmcp"
        ),
        language="rust",
        seed_globs=("**/lib.rs", "**/main.rs", "**/*.rs"),
    ),
    Target(
        name="express-ts",
        project_id="express-client-smoke",
        source=os.environ.get(
            "EXPRESS_SOURCE", "https://github.com/expressjs/express"
        ),
        language="typescript",
        seed_globs=("lib/**/*.js", "index.js", "**/*.js", "**/*.ts"),
    ),
)


def unwrap(result: Any) -> Any:
    if hasattr(result, "data") and result.data is not None:
        return result.data
    if hasattr(result, "content"):
        content = result.content
        if isinstance(content, list) and content:
            texts = [
                getattr(b, "text", None)
                for b in content
                if getattr(b, "text", None)
            ]
            if len(texts) == 1:
                try:
                    return json.loads(texts[0])
                except Exception:
                    return texts[0]
            return texts or content
    return result


async def call(client: Client, name: str, args: dict | None = None) -> Any:
    return unwrap(await client.call_tool(name, args or {}))


async def call_task(client: Client, name: str, args: dict | None = None) -> Any:
    task = await client.call_tool(name, args or {}, task=True)
    print(
        f"    task {name}: id={getattr(task, 'task_id', None)}",
        flush=True,
    )
    return unwrap(await task.result())


def _ok_payload(payload: Any) -> bool:
    return not (isinstance(payload, dict) and payload.get("error"))


async def run_target(client: Client, t: Target) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": t.name,
        "project_id": t.project_id,
        "language": t.language,
        "source": t.source,
        "ok": False,
        "steps": {},
    }
    print(f"\n======== {t.name} ({t.language}) ========", flush=True)

    created = await call(client, "create_session", {"meta": f"prod-smoke-{t.name}"})
    entry["steps"]["create_session"] = created
    if not _ok_payload(created) or "session_id" not in created:
        entry["failed_at"] = "create_session"
        return entry
    sid = created["session_id"]

    imported = await call_task(
        client,
        "import_project",
        {"project_id": t.project_id, "source": t.source},
    )
    entry["steps"]["import_project"] = imported
    if isinstance(imported, dict) and imported.get("error") == "project_exists":
        print(f"    reuse project {t.project_id}", flush=True)
    elif not _ok_payload(imported):
        entry["failed_at"] = "import_project"
        return entry

    checkout = await call(
        client,
        "checkout_workspace",
        {"session_id": sid, "project_id": t.project_id},
    )
    entry["steps"]["checkout_workspace"] = checkout
    if not _ok_payload(checkout):
        entry["failed_at"] = "checkout_workspace"
        return entry

    runtime = await call_task(
        client,
        "ensure_runtime",
        {
            "session_id": sid,
            "language": t.language,
            "prefer_container": True,
        },
    )
    entry["steps"]["ensure_runtime"] = runtime
    if not _ok_payload(runtime):
        entry["failed_at"] = "ensure_runtime"
        return entry
    if isinstance(runtime, dict) and runtime.get("runtime_mode") != "container":
        entry["failed_at"] = "ensure_runtime_not_container"
        return entry

    warm = await call_task(
        client,
        "warm_index",
        {"session_id": sid, "timeout_seconds": WARM_TIMEOUT},
    )
    entry["steps"]["warm_index"] = warm
    if not _ok_payload(warm):
        entry["failed_at"] = "warm_index"
        return entry
    if isinstance(warm, dict) and warm.get("index_status") != "ready":
        entry["failed_at"] = "warm_index_not_ready"
        return entry

    # Best-effort symbol probe (clangd without compile_commands may be sparse).
    ws = Path(checkout["path"]) if isinstance(checkout, dict) else None
    seed = None
    if ws and ws.is_dir():
        for pattern in t.seed_globs:
            for p in ws.glob(pattern):
                if p.is_file() and "node_modules" not in p.parts and "target" not in p.parts:
                    seed = p.relative_to(ws).as_posix()
                    break
            if seed:
                break
    entry["seed"] = seed
    if seed:
        symbols = await call(
            client, "list_symbols", {"session_id": sid, "file_path": seed}
        )
        entry["steps"]["list_symbols"] = (
            symbols
            if not isinstance(symbols, dict)
            else {
                "count": len(symbols.get("symbols") or []),
                "error": symbols.get("error"),
            }
        )
        syms = symbols.get("symbols") if isinstance(symbols, dict) else None
        if syms:
            s0 = syms[0]
            explore = await call(
                client,
                "explore_symbol",
                {
                    "session_id": sid,
                    "file_path": seed,
                    "line": s0["line"],
                    "column": s0["character"] + 1,
                },
            )
            entry["steps"]["explore_symbol"] = (
                explore
                if not isinstance(explore, dict)
                else {
                    "name": explore.get("name") or explore.get("symbol"),
                    "error": explore.get("error"),
                }
            )

    entry["ok"] = True
    print(f"    OK {t.language} container warm_index=ready seed={seed}", flush=True)
    return entry


async def main() -> int:
    if not TOKEN:
        print("AGENT_LSP_BEARER_TOKEN is required", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "url": URL,
        "targets": [],
        "ok": True,
        "prompts": None,
        "tools_count": None,
    }

    async with Client(URL, auth=TOKEN) as client:
        tools = await client.list_tools()
        report["tools_count"] = len(tools)
        print(f"tools: {len(tools)}", flush=True)

        try:
            prompts = await client.list_prompts()
            names = sorted(getattr(p, "name", str(p)) for p in prompts)
            report["prompts"] = names
            print(f"prompts: {names}", flush=True)
        except Exception as exc:  # noqa: BLE001
            report["prompts_error"] = str(exc)
            print(f"prompts: error {exc}", flush=True)

        selected = [
            t
            for t in TARGETS
            if not ONLY
            or t.language in ONLY
            or t.name in ONLY
            or t.project_id in ONLY
        ]
        for t in selected:
            try:
                entry = await run_target(client, t)
            except Exception as exc:  # noqa: BLE001
                entry = {
                    "name": t.name,
                    "language": t.language,
                    "ok": False,
                    "failed_at": "exception",
                    "error": str(exc),
                }
                print(f"    FAIL exception: {exc}", flush=True)
            report["targets"].append(entry)
            if not entry.get("ok"):
                report["ok"] = False

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"\n==== REPORT → {REPORT_PATH} ok={report['ok']} ====", flush=True)
    for t in report["targets"]:
        mark = "PASS" if t.get("ok") else f"FAIL@{t.get('failed_at')}"
        print(f"  {mark:20} {t.get('name')} ({t.get('language')})", flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
