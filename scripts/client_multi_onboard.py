#!/usr/bin/env python3
"""FastMCP client smoke for one or more real projects via agent-lsp.

Default targets:
  - hewimetall/vmcp (rust)
  - Bogdanp/dramatiq (python)

Usage:
  uv run python scripts/client_multi_onboard.py
  CLIENT_PREFER_CONTAINER=1 uv run python scripts/client_multi_onboard.py
  CLIENT_ONLY=dramatiq uv run python scripts/client_multi_onboard.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Isolate scout state for this run (before importing server).
_ROOT = Path(tempfile.mkdtemp(prefix="agent-lsp-multi-client-"))
os.environ["AGENT_LSP_STATE"] = str(_ROOT / "state")
os.environ["AGENT_LSP_PROJECTS"] = str(_ROOT / "projects")
os.environ["AGENT_LSP_WORKSPACES"] = str(_ROOT / "workspaces")
os.environ["AGENT_LSP_CACHE"] = str(_ROOT / "cache")

from fastmcp import Client  # noqa: E402

from agent_lsp import paths as paths_mod  # noqa: E402
from agent_lsp.server import mcp  # noqa: E402


@dataclass(frozen=True)
class Target:
    name: str
    project_id: str
    source: str
    language: str
    seed_globs: tuple[str, ...]


DEFAULT_TARGETS: tuple[Target, ...] = (
    Target(
        name="vmcp",
        project_id="vmcp",
        source=os.environ.get("VMCP_SOURCE", "/tmp/client-srcs/vmcp"),
        language="rust",
        seed_globs=("**/lib.rs", "**/main.rs", "**/*.rs"),
    ),
    Target(
        name="dramatiq",
        project_id="dramatiq",
        source=os.environ.get("DRAMATIQ_SOURCE", "/tmp/client-srcs/dramatiq"),
        language="python",
        seed_globs=("dramatiq/actor.py", "dramatiq/**/*.py", "**/*.py"),
    ),
)

PREFER_CONTAINER = os.environ.get("CLIENT_PREFER_CONTAINER", "0") not in (
    "0",
    "false",
    "False",
    "",
)
ONLY = os.environ.get("CLIENT_ONLY", "").strip().lower()
REPORT_PATH = Path(
    os.environ.get("CLIENT_REPORT", "/opt/cursor/artifacts/multi-client-report.json")
)

REPORT: dict[str, Any] = {
    "data_root": str(_ROOT),
    "prefer_container": PREFER_CONTAINER,
    "targets": [],
    "ok": True,
}


def _log(target: str, step: str, payload: Any) -> None:
    print(f"\n=== [{target}] {step} ===", flush=True)
    print(json.dumps(payload, indent=2, default=str)[:4000], flush=True)


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
    result = await client.call_tool(name, arguments or {})
    return _unwrap(result)


async def _call_task(
    client: Client, name: str, arguments: dict[str, Any] | None = None
) -> Any:
    task = await client.call_tool(name, arguments or {}, task=True)
    print(
        f"  task meta: id={getattr(task, 'task_id', None)} "
        f"immediate={getattr(task, 'returned_immediately', None)}",
        flush=True,
    )
    result = await task.result()
    return _unwrap(result)


def _pick_seed(ws: Path, globs: tuple[str, ...]) -> str | None:
    for pattern in globs:
        for p in ws.glob(pattern):
            if (
                p.is_file()
                and "node_modules" not in p.parts
                and "target" not in p.parts
                and ".venv" not in p.parts
                and "tests" not in p.parts
            ):
                return p.relative_to(ws).as_posix()
    # fallback: allow tests/
    for pattern in globs:
        for p in ws.glob(pattern):
            if p.is_file() and "node_modules" not in p.parts and "target" not in p.parts:
                return p.relative_to(ws).as_posix()
    return None


async def onboard_one(client: Client, target: Target) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": target.name,
        "project_id": target.project_id,
        "source": target.source,
        "language": target.language,
        "prefer_container": PREFER_CONTAINER,
        "steps": [],
        "ok": False,
    }

    def rec(step: str, payload: Any) -> None:
        entry["steps"].append({"step": step, "result": payload})
        _log(target.name, step, payload)

    created = await _call(client, "create_session", {"meta": f"client-{target.name}"})
    rec("create_session", created)
    if not isinstance(created, dict) or "session_id" not in created:
        entry["failed_at"] = "create_session"
        return entry
    sid = created["session_id"]

    imported = await _call_task(
        client,
        "import_project",
        {"project_id": target.project_id, "source": target.source},
    )
    rec("import_project", imported)
    if isinstance(imported, dict) and imported.get("error"):
        entry["failed_at"] = "import_project"
        return entry

    checkout = await _call(
        client,
        "checkout_workspace",
        {"session_id": sid, "project_id": target.project_id},
    )
    rec("checkout_workspace", checkout)
    if isinstance(checkout, dict) and checkout.get("error"):
        entry["failed_at"] = "checkout_workspace"
        return entry
    ws_path = Path(checkout["path"])

    runtime = await _call_task(
        client,
        "ensure_runtime",
        {
            "session_id": sid,
            "language": target.language,
            "prefer_container": PREFER_CONTAINER,
        },
    )
    rec("ensure_runtime", runtime)
    if isinstance(runtime, dict) and (
        runtime.get("error") or runtime.get("status") == "error"
    ):
        entry["failed_at"] = "ensure_runtime"
        return entry

    warm = await _call_task(
        client,
        "warm_index",
        {"session_id": sid, "timeout_seconds": 240.0},
    )
    rec("warm_index", warm)
    if not isinstance(warm, dict) or warm.get("index_status") != "ready":
        entry["failed_at"] = "warm_index"
        return entry

    session = await _call(client, "get_session", {"session_id": sid})
    rec("get_session", session)

    seed = _pick_seed(ws_path, target.seed_globs)
    rec("seed_file", {"seed": seed, "workspace": str(ws_path)})
    if seed:
        symbols = await _call(
            client, "list_symbols", {"session_id": sid, "file_path": seed}
        )
        rec("list_symbols", symbols)
        syms = symbols.get("symbols") if isinstance(symbols, dict) else None
        if syms:
            # Prefer a function/class-like symbol over a module namespace when possible.
            pick = next(
                (s for s in syms if int(s.get("kind") or 0) in {5, 6, 12, 13, 23, 26}),
                syms[0],
            )
            try:
                explore = await _call(
                    client,
                    "explore_symbol",
                    {
                        "session_id": sid,
                        "file_path": seed,
                        "line": pick["line"],
                        "column": pick["character"] + 1,
                    },
                )
                rec("explore_symbol", {"picked": pick, "result": explore})
            except Exception as exc:  # noqa: BLE001
                rec("explore_symbol", {"picked": pick, "error": str(exc)})
            blast = await _call(
                client,
                "blast_radius",
                {
                    "session_id": sid,
                    "changed_files": [seed],
                    "include_transitive": False,
                },
            )
            rec("blast_radius", blast)

    closed = await _call(client, "close_session", {"session_id": sid})
    rec("close_session", closed)
    entry["ok"] = True
    return entry


async def main() -> int:
    paths_mod.STATE_DIR = Path(os.environ["AGENT_LSP_STATE"])
    paths_mod.PROJECTS_DIR = Path(os.environ["AGENT_LSP_PROJECTS"])
    paths_mod.WORKSPACES_DIR = Path(os.environ["AGENT_LSP_WORKSPACES"])
    paths_mod.CACHE_DIR = Path(os.environ["AGENT_LSP_CACHE"])
    paths_mod.ensure_data_dirs()

    from agent_lsp import server as server_mod

    if not PREFER_CONTAINER:
        server_mod._docker = None
        server_mod._docker_error = "disabled-prefer-local"
    else:
        # Force fresh docker probe.
        server_mod._docker = None
        server_mod._docker_error = None

    targets = [t for t in DEFAULT_TARGETS if not ONLY or t.name == ONLY]
    if not targets:
        print(f"no targets matched CLIENT_ONLY={ONLY!r}", file=sys.stderr)
        return 2

    async with Client(mcp) as client:
        tools = await client.list_tools()
        print(
            f"tools={len(tools)} prefer_container={PREFER_CONTAINER} "
            f"targets={[t.name for t in targets]}",
            flush=True,
        )
        for target in targets:
            src = Path(target.source)
            if not src.exists():
                entry = {
                    "name": target.name,
                    "ok": False,
                    "failed_at": "source_missing",
                    "source": target.source,
                }
                REPORT["targets"].append(entry)
                REPORT["ok"] = False
                _log(target.name, "source_missing", entry)
                continue
            try:
                entry = await onboard_one(client, target)
            except Exception as exc:  # noqa: BLE001
                entry = {
                    "name": target.name,
                    "ok": False,
                    "failed_at": "exception",
                    "exception": str(exc),
                    "traceback": traceback.format_exc(),
                }
                _log(target.name, "exception", entry)
            REPORT["targets"].append(entry)
            if not entry.get("ok"):
                REPORT["ok"] = False

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(REPORT, indent=2, default=str))
    print(f"\nREPORT → {REPORT_PATH}", flush=True)
    summary = {
        "ok": REPORT["ok"],
        "prefer_container": PREFER_CONTAINER,
        "results": [
            {
                "name": t.get("name"),
                "ok": t.get("ok"),
                "failed_at": t.get("failed_at"),
                "language": t.get("language"),
                "runtime_mode": next(
                    (
                        s["result"].get("runtime_mode")
                        for s in t.get("steps", [])
                        if s.get("step") == "ensure_runtime"
                        and isinstance(s.get("result"), dict)
                    ),
                    None,
                ),
            }
            for t in REPORT["targets"]
        ],
    }
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if REPORT["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
