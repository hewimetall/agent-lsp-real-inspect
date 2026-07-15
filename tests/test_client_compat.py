"""Client capability / Cursor detection helpers."""

from __future__ import annotations

from types import SimpleNamespace

from agent_lsp.client_compat import (
    client_has_tasks_capability,
    is_cursor_client,
    prefers_progress_over_tasks,
)


def _ctx(name: str, *, tasks: bool = False) -> SimpleNamespace:
    caps = SimpleNamespace(tasks=object() if tasks else None)
    params = SimpleNamespace(
        clientInfo=SimpleNamespace(name=name, version="1.0.0"),
        capabilities=caps,
    )
    session = SimpleNamespace(client_params=params)
    return SimpleNamespace(session=session)


def test_is_cursor_client_by_name() -> None:
    assert is_cursor_client(name="cursor-vscode")
    assert is_cursor_client(name="Cursor")
    assert is_cursor_client(name="cursor-agent")
    assert not is_cursor_client(name="claude-code")
    assert not is_cursor_client(name="")


def test_prefers_progress_for_cursor_even_with_tasks_flag() -> None:
    # Cursor must use progress path regardless of accidental caps.
    assert prefers_progress_over_tasks(_ctx("cursor-vscode", tasks=True))
    assert prefers_progress_over_tasks(_ctx("Cursor", tasks=False))


def test_prefers_progress_when_no_tasks_capability() -> None:
    assert prefers_progress_over_tasks(_ctx("vmcp-lite", tasks=False))
    assert not prefers_progress_over_tasks(_ctx("vmcp", tasks=True))


def test_client_has_tasks_capability() -> None:
    assert client_has_tasks_capability(_ctx("x", tasks=True))
    assert not client_has_tasks_capability(_ctx("x", tasks=False))
    assert not client_has_tasks_capability(None)
