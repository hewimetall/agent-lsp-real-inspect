"""Bridge MCP/FastMCP background tasks ↔ durable SQLite TaskStore.

Docket/memory is only the SEP-1686 wait + notifications layer.
Durable queue stays on ``agent_lsp._tasks.TaskStore`` (ADR-0003).
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Protocol, cast

from agent_lsp._tasks import TaskStore

POLL_SECONDS = float(os.environ.get("AGENT_LSP_TASK_BRIDGE_POLL_SECONDS", "0.25"))
WAIT_TIMEOUT = float(os.environ.get("AGENT_LSP_TASK_WAIT_TIMEOUT", "600"))
_STATUS_ERROR_MAX = 240
TERMINAL = frozenset({"done", "error"})


class ProgressReporter(Protocol):
    async def set_message(self, message: str | None) -> None: ...


def _as_row(row: object) -> dict[str, Any]:
    return cast(dict[str, Any], dict(row))  # type: ignore[arg-type]


def _short_error(err: str) -> str:
    text = " ".join(err.split())
    if len(text) <= _STATUS_ERROR_MAX:
        return text
    return text[: _STATUS_ERROR_MAX - 3] + "..."


def status_message(row: dict[str, Any]) -> str:
    """Human status line that always carries our SQLite task_id."""
    tid = row["task_id"]
    status = row["status"]
    err = row.get("error")
    if status == "error" and err:
        return f"task_id={tid} status=error error={_short_error(str(err))}"
    if status == "done":
        return f"task_id={tid} status=done"
    return f"task_id={tid} status={status}"


async def await_sqlite_task(
    tasks: TaskStore,
    task_id: str,
    progress: ProgressReporter | None = None,
    *,
    poll_seconds: float = POLL_SECONDS,
    timeout: float = WAIT_TIMEOUT,
) -> dict[str, Any]:
    """Poll SQLite until terminal status; mirror each change via Progress.

    Progress messages become ``notifications/tasks/status`` when the tool runs
    as an MCP background task (client ``task=True``).
    """
    last: str | None = None
    deadline = time.monotonic() + timeout
    while True:
        raw = await asyncio.to_thread(tasks.get, task_id)
        if raw is None:
            msg = f"task_id={task_id} status=missing"
            if progress is not None:
                await progress.set_message(msg)
            raise LookupError(f"task not found: {task_id}")
        row = _as_row(raw)
        msg = status_message(row)
        if msg != last and progress is not None:
            await progress.set_message(msg)
            last = msg
        if row["status"] in TERMINAL:
            return row
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"task_id={task_id} wait timed out after {timeout:.0f}s "
                f"(last status={row['status']})"
            )
        await asyncio.sleep(poll_seconds)
