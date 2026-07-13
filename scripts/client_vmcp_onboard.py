#!/usr/bin/env python3
"""FastMCP client smoke: onboard hewimetall/vmcp via agent-lsp happy path.

Exercises create_session → import_project(task=True) → checkout_workspace →
ensure_runtime(task=True, local) → warm_index(task=True) → scout tools.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

# Isolate scout state for this run (before importing server).
_ROOT = Path(tempfile.mkdtemp(prefix="agent-lsp-vmcp-client-"))
os.environ["AGENT_LSP_STATE"] = str(_ROOT / "state")
os.environ["AGENT_LSP_PROJECTS"] = str(_ROOT / "projects")
os.environ["AGENT_LSP_WORKSPACES"] = str(_ROOT / "workspaces")
os.environ["AGENT_LSP_CACHE"] = str(_ROOT / "cache")

from fastmcp import Client  # noqa: E402

from agent_lsp import paths as paths_mod  # noqa: E402
from agent_lsp.server import mcp  # noqa: E402

VMCP_URL = os.environ.get("VMCP_SOURCE", "https://github.com/hewimetall/vmcp")
PROJECT_ID = os.environ.get("VMCP_PROJECT_ID", "vmcp")
LANGUAGE = os.environ.get("VMCP_LANGUAGE", "rust")

REPORT: dict[str, Any] = {
    "data_root": str(_ROOT),
    "source": VMCP_URL,
    "project_id": PROJECT_ID,
    "language": LANGUAGE,
    "steps": [],
}


def _log(step: str, payload: Any) -> None:
    entry = {"step": step, "result": payload}
    REPORT["steps"].append(entry)
    print(f"\n=== {step} ===", flush=True)
    print(json.dumps(payload, indent=2, default=str)[:4000], flush=True)


def _unwrap(result: Any) -> Any:
    """Normalize FastMCP CallToolResult / ToolTask payload."""
    if hasattr(result, "data") and result.data is not None:
        return result.data
    if hasattr(result, "content"):
        content = result.content
        if isinstance(content, list) and content:
            texts = []
            for block in content:
                text = getattr(block, "text", None)
                if text:
                    texts.append(text)
            if len(texts) == 1:
                try:
                    return json.loads(texts[0])
                except (json.JSONDecodeError, TypeError):
                    return texts[0]
            return texts or content
    return result


async def _call(client: Client, name: str, arguments: dict[str, Any] | None = None) -> Any:
    result = await client.call_tool(name, arguments or {})
    return _unwrap(result)


async def _call_task(
    client: Client, name: str, arguments: dict[str, Any] | None = None
) -> Any:
    task = await client.call_tool(name, arguments or {}, task=True)
    task_meta = {
        "task_id": getattr(task, "task_id", None),
        "returned_immediately": getattr(task, "returned_immediately", None),
    }
    print(f"  task meta: {task_meta}", flush=True)
    result = await task.result()
    return _unwrap(result)


async def main() -> int:
    # Point path helpers at the isolated dirs (module may already be imported).
    paths_mod.STATE_DIR = Path(os.environ["AGENT_LSP_STATE"])
    paths_mod.PROJECTS_DIR = Path(os.environ["AGENT_LSP_PROJECTS"])
    paths_mod.WORKSPACES_DIR = Path(os.environ["AGENT_LSP_WORKSPACES"])
    paths_mod.CACHE_DIR = Path(os.environ["AGENT_LSP_CACHE"])
    paths_mod.ensure_data_dirs()

    # Force local LSP (no Docker in this environment).
    from agent_lsp import server as server_mod

    server_mod._docker = None
    server_mod._docker_error = "disabled-for-vmcp-client-smoke"

    async with Client(mcp) as client:
        tools = await client.list_tools()
        tool_names = sorted(t.name for t in tools)
        _log("list_tools", {"count": len(tool_names), "tools": tool_names})

        created = await _call(client, "create_session", {"meta": "vmcp-client-smoke"})
        _log("create_session", created)
        sid = created["session_id"]

        imported = await _call_task(
            client,
            "import_project",
            {"project_id": PROJECT_ID, "source": VMCP_URL},
        )
        _log("import_project", imported)
        if isinstance(imported, dict) and imported.get("error"):
            REPORT["ok"] = False
            REPORT["failed_at"] = "import_project"
            return 1

        checkout = await _call(
            client,
            "checkout_workspace",
            {"session_id": sid, "project_id": PROJECT_ID},
        )
        _log("checkout_workspace", checkout)
        if isinstance(checkout, dict) and checkout.get("error"):
            REPORT["ok"] = False
            REPORT["failed_at"] = "checkout_workspace"
            return 1
        ws_path = Path(checkout["path"])

        # Prefer local rust-analyzer (Docker unavailable).
        runtime = await _call_task(
            client,
            "ensure_runtime",
            {
                "session_id": sid,
                "language": LANGUAGE,
                "prefer_container": False,
            },
        )
        _log("ensure_runtime", runtime)
        if isinstance(runtime, dict) and runtime.get("error"):
            REPORT["ok"] = False
            REPORT["failed_at"] = "ensure_runtime"
            return 1

        warm = await _call_task(
            client,
            "warm_index",
            {"session_id": sid, "timeout_seconds": 180.0},
        )
        _log("warm_index", warm)
        if isinstance(warm, dict) and (
            warm.get("error") or warm.get("index_status") not in (None, "ready")
        ):
            # warm_index returns index_status=ready on success
            if warm.get("index_status") != "ready":
                REPORT["ok"] = False
                REPORT["failed_at"] = "warm_index"
                return 1

        session = await _call(client, "get_session", {"session_id": sid})
        _log("get_session", session)

        # Find a Rust seed file for scout probes.
        seed = None
        for pattern in ("**/lib.rs", "**/main.rs", "**/*.rs"):
            for p in ws_path.glob(pattern):
                if p.is_file() and "target" not in p.parts:
                    seed = p.relative_to(ws_path).as_posix()
                    break
            if seed:
                break
        _log("seed_file", {"seed": seed, "workspace": str(ws_path)})

        if seed:
            symbols = await _call(
                client, "list_symbols", {"session_id": sid, "file_path": seed}
            )
            _log("list_symbols", symbols)

            # Probe first symbol if present.
            syms = symbols.get("symbols") if isinstance(symbols, dict) else None
            if syms:
                s0 = syms[0]
                explore = await _call(
                    client,
                    "explore_symbol",
                    {
                        "session_id": sid,
                        "file_path": seed,
                        "line": s0["line"],
                        "column": s0["character"] + 1,
                    },
                )
                _log("explore_symbol", explore)

                blast = await _call(
                    client,
                    "blast_radius",
                    {
                        "session_id": sid,
                        "changed_files": [seed],
                        "include_transitive": False,
                    },
                )
                _log("blast_radius", blast)

        closed = await _call(client, "close_session", {"session_id": sid})
        _log("close_session", closed)

    REPORT["ok"] = True
    return 0


if __name__ == "__main__":
    code = 1
    try:
        code = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        REPORT["ok"] = False
        REPORT["exception"] = str(exc)
        REPORT["traceback"] = traceback.format_exc()
        print(REPORT["traceback"], file=sys.stderr)
        code = 1
    out = Path(os.environ.get("VMCP_CLIENT_REPORT", "/tmp/vmcp-client-report.json"))
    out.write_text(json.dumps(REPORT, indent=2, default=str))
    print(f"\nREPORT written to {out}", flush=True)
    print(json.dumps({"ok": REPORT.get("ok"), "failed_at": REPORT.get("failed_at")}, indent=2))
    raise SystemExit(code)
