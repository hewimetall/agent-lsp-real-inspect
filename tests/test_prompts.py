"""MCP prompts registration (important scout flows only)."""

from __future__ import annotations

import asyncio

from fastmcp import FastMCP

from agent_lsp.prompts import register_prompts


def test_register_prompts_lists_important_names() -> None:
    mcp = FastMCP("test-prompts")
    register_prompts(mcp)

    async def _list() -> set[str]:
        rows = await mcp.list_prompts()
        return {p.name for p in rows}

    names = asyncio.run(_list())
    assert {"onboard", "mirror", "explore", "impact", "safe_edit", "verify"} <= names
    assert "refactor" not in names


def test_onboard_prompt_renders_fields() -> None:
    mcp = FastMCP("test-prompts-2")
    register_prompts(mcp)

    async def _get() -> str:
        prompt = await mcp.get_prompt("onboard")
        assert prompt is not None
        result = await prompt.render(
            {
                "project_id": "demo",
                "source": "https://github.com/example/demo.git",
                "language": "python",
                "language_version": "3.12",
            }
        )
        text = result.messages[0].content.text  # type: ignore[union-attr]
        return str(text)

    text = asyncio.run(_get())
    assert "demo" in text
    assert "create_session" in text
    assert "import_project" in text


def test_server_registers_prompts_on_import() -> None:
    from agent_lsp import server

    names = asyncio.run(server.mcp.list_prompts())
    assert any(p.name == "onboard" for p in names)
    assert any(p.name == "explore" for p in names)
