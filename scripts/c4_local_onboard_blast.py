#!/usr/bin/env python3
"""Local agent-lsp onboard of this repo + blast_radius for C4 code level.

Requires AGENT_LSP_ALLOW_LOCAL=1 and host pyright-langserver.
Writes /opt/cursor/artifacts/c4-local-blast.json
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / ".data"
for key, sub in (
    ("AGENT_LSP_STATE", "state"),
    ("AGENT_LSP_PROJECTS", "projects"),
    ("AGENT_LSP_WORKSPACES", "workspaces"),
    ("AGENT_LSP_CACHE", "cache"),
):
    p = DATA / sub
    p.mkdir(parents=True, exist_ok=True)
    os.environ[key] = str(p)

os.environ["AGENT_LSP_ALLOW_LOCAL"] = "1"
# Prefer host pyright from venv
os.environ.setdefault(
    "PATH",
    f"{ROOT / '.venv' / 'bin'}:{os.environ.get('PATH', '')}",
)

from fastmcp import Client  # noqa: E402

from agent_lsp.server import mcp  # noqa: E402

REPORT_PATH = Path(
    os.environ.get("C4_BLAST_REPORT", "/opt/cursor/artifacts/c4-local-blast.json")
)

# Seed symbols for blast / explore (path relative to worktree, 1-based).
TARGETS: list[dict[str, Any]] = [
    {
        "id": "code-runtime-hub",
        "label": "RuntimeHub",
        "path": "python/agent_lsp/runtime_hub.py",
        "symbol_hint": "class RuntimeHub",
    },
    {
        "id": "code-lsp-client",
        "label": "LspClient",
        "path": "python/agent_lsp/lsp_client.py",
        "symbol_hint": "class LspClient",
    },
    {
        "id": "code-server-mcp",
        "label": "FastMCP server tools",
        "path": "python/agent_lsp/server.py",
        "symbol_hint": "def blast_radius_tool",
    },
    {
        "id": "code-worker",
        "label": "ScoutWorker",
        "path": "python/agent_lsp/worker.py",
        "symbol_hint": "class ScoutWorker",
    },
    {
        "id": "code-task-bridge",
        "label": "await_sqlite_task",
        "path": "python/agent_lsp/task_bridge.py",
        "symbol_hint": "async def await_sqlite_task",
    },
    {
        "id": "code-blast",
        "label": "blast_radius",
        "path": "python/agent_lsp/blast.py",
        "symbol_hint": "def blast_radius",
    },
]


def _unwrap(result: Any) -> Any:
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
    return _unwrap(await client.call_tool(name, arguments or {}))


async def _call_task(
    client: Client, name: str, arguments: dict[str, Any] | None = None
) -> Any:
    # Cursor-style: ordinary call + progress (TaskConfig optional)
    return _unwrap(await client.call_tool(name, arguments or {}))


def _find_line(worktree: Path, rel: str, hint: str) -> int:
    text = (worktree / rel).read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        if hint in line:
            return i
    return 1


async def main() -> int:
    report: dict[str, Any] = {"ok": False, "steps": {}, "blasts": [], "explores": []}
    async with Client(mcp) as client:
        sess = await _call(client, "create_session", {"meta": "c4-local-code-level"})
        sid = sess["session_id"] if isinstance(sess, dict) else sess
        report["session_id"] = sid
        print(f"session={sid}", flush=True)

        imp = await _call_task(
            client,
            "import_project",
            {"project_id": "agent-lsp-self", "source": str(ROOT)},
        )
        report["steps"]["import_project"] = imp
        print("import_project ok", flush=True)

        ws = await _call(
            client,
            "checkout_workspace",
            {
                "session_id": sid,
                "project_id": "agent-lsp-self",
                "ref_name": "HEAD",
            },
        )
        report["steps"]["checkout_workspace"] = ws
        ws_id = ws.get("workspace_id") if isinstance(ws, dict) else None
        worktree = Path(ws["path"]) if isinstance(ws, dict) and "path" in ws else None
        print(f"checkout workspace_id={ws_id} path={worktree}", flush=True)

        rt = await _call_task(
            client,
            "ensure_runtime",
            {
                "session_id": sid,
                "language": "python",
                "prefer_container": False,
                "language_version": "3.12",
            },
        )
        report["steps"]["ensure_runtime"] = rt
        print(f"ensure_runtime={rt}", flush=True)

        warm = await _call_task(client, "warm_index", {"session_id": sid})
        report["steps"]["warm_index"] = warm
        print(f"warm_index={warm}", flush=True)

        if worktree is None:
            # resolve from session
            g = await _call(client, "get_session", {"session_id": sid})
            report["session"] = g
            aw = (g or {}).get("active_workspace_id")
            if aw:
                worktree = Path(os.environ["AGENT_LSP_WORKSPACES"]) / aw

        assert worktree is not None and worktree.is_dir(), worktree

        for t in TARGETS:
            line = _find_line(worktree, t["path"], t["symbol_hint"])
        try:
            br = await _call(
                client,
                "blast_radius",
                {
                    "session_id": sid,
                    "changed_files": [t["path"] for t in TARGETS],
                    "include_transitive": True,
                },
            )
            report["blasts"] = br
            print("blast_radius ok", flush=True)
        except Exception as exc:  # noqa: BLE001
            report["blasts"] = {"error": str(exc)}
            print(f"blast_radius ERR {exc}", flush=True)

        for t in TARGETS:
            line = _find_line(worktree, t["path"], t["symbol_hint"])
            text = (worktree / t["path"]).read_text(encoding="utf-8").splitlines()[
                line - 1
            ]
            col = max(1, text.find(t["symbol_hint"].split()[-1]) + 1)
            try:
                ex = await _call(
                    client,
                    "explore_symbol",
                    {
                        "session_id": sid,
                        "file_path": t["path"],
                        "line": line,
                        "column": col,
                    },
                )
                report["explores"].append(
                    {"target": t, "line": line, "column": col, "result": ex}
                )
                print(f"explore {t['id']}@{line}:{col} ok", flush=True)
            except Exception as exc:  # noqa: BLE001
                report["explores"].append({"target": t, "line": line, "error": str(exc)})
                print(f"explore {t['id']} ERR {exc}", flush=True)

        report["ok"] = True
        report["worktree"] = str(worktree)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"wrote {REPORT_PATH}", flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
