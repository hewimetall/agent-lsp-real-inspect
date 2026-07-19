"""Client capability / Cursor detection helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_lsp.client_compat import (
    client_capabilities_dict,
    client_has_tasks_capability,
    client_info_dict,
    is_cursor_client,
    log_client_initialize,
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


def test_client_info_and_capabilities_dict() -> None:
    assert client_info_dict(None) == {}
    assert client_capabilities_dict(None) == {}
    ctx = _ctx("cursor-vscode", tasks=True)
    info = client_info_dict(ctx)
    assert info["name"] == "cursor-vscode"
    assert info["version"] == "1.0.0"
    caps = client_capabilities_dict(ctx)
    assert "raw" in caps or caps  # SimpleNamespace → raw repr path


def test_force_progress_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_LSP_FORCE_PROGRESS_CLIENTS", "1")
    assert prefers_progress_over_tasks(_ctx("vmcp", tasks=True))
    monkeypatch.delenv("AGENT_LSP_FORCE_PROGRESS_CLIENTS", raising=False)
    assert not prefers_progress_over_tasks(_ctx("vmcp", tasks=True))


def test_log_client_initialize_does_not_raise() -> None:
    caps = SimpleNamespace(tasks=object(), roots=object(), experimental={"x": 1})
    log_client_initialize(name="cursor-vscode", version="1", capabilities=caps)
    log_client_initialize(name=None, version=None, capabilities=None)


def test_is_cursor_client_from_ctx() -> None:
    assert is_cursor_client(_ctx("cursor-agent"))
    assert not is_cursor_client(_ctx("claude"))
    assert prefers_progress_over_tasks(None) is False
