"""FastMCP middleware: log clientInfo; adapt taskSupport for Cursor."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

import mcp.types as mt
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool
from fastmcp.utilities.tasks import TaskConfig
from mcp.types import ToolExecution

from agent_lsp.client_compat import (
    SCOUT_LONG_TOOLS,
    log_client_initialize,
    prefers_progress_over_tasks,
)

_PROGRESS_TASK = TaskConfig(mode="forbidden", poll_interval=timedelta(seconds=1))


class ClientCompatMiddleware(Middleware):
    """Log initialize identity; for Cursor-like clients advertise progress-only tools."""

    async def on_initialize(
        self,
        context: MiddlewareContext[mt.InitializeRequest],
        call_next: CallNext[mt.InitializeRequest, mt.InitializeResult | None],
    ) -> mt.InitializeResult | None:
        params = getattr(context.message, "params", None)
        info = getattr(params, "clientInfo", None) if params is not None else None
        caps = getattr(params, "capabilities", None) if params is not None else None
        log_client_initialize(
            name=getattr(info, "name", None) if info is not None else None,
            version=getattr(info, "version", None) if info is not None else None,
            capabilities=caps,
        )
        return await call_next(context)

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        ctx = context.fastmcp_context
        if not prefers_progress_over_tasks(ctx):
            return tools
        adapted: list[Tool] = []
        for tool in tools:
            if tool.name not in SCOUT_LONG_TOOLS:
                adapted.append(tool)
                continue
            # Cursor has no Tasks API — advertise forbidden so the IDE uses
            # ordinary tools/call + notifications/progress.
            adapted.append(
                tool.model_copy(
                    update={
                        "task_config": _PROGRESS_TASK,
                        "execution": ToolExecution(taskSupport="forbidden"),
                    }
                )
            )
        return adapted
