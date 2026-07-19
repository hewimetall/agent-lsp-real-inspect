"""CLI entrypoint: --help / --version must not start the MCP server."""

from __future__ import annotations

import pytest

import agent_lsp
from agent_lsp import _version
from agent_lsp.server import main


def _boom(*_a: object, **_k: object) -> None:
    raise AssertionError("mcp.run must not be called")


def test_package_exposes_version() -> None:
    assert isinstance(agent_lsp.__version__, str)
    assert agent_lsp.__version__
    assert agent_lsp.__version__ != "?"
    assert agent_lsp.__version__ != "0.0.0+unknown"
    assert agent_lsp.__version__ == _version.package_version()


def test_package_version_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from importlib.metadata import PackageNotFoundError

    def missing(_name: str) -> str:
        raise PackageNotFoundError(_name)

    monkeypatch.setattr(_version, "version", missing)
    assert _version.package_version() == "0.0.0+unknown"


def test_help_prints_usage_and_does_not_run_mcp(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        "agent_lsp.server.mcp.run", lambda *a, **k: called.append("run")
    )
    monkeypatch.setattr(
        "agent_lsp.server.ensure_data_dirs", lambda: called.append("dirs")
    )

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "usage: agent-lsp" in out
    assert "--version" in out
    assert called == []


def test_version_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("agent_lsp.server.mcp.run", _boom)
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == agent_lsp.__version__


def test_unexpected_args_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("agent_lsp.server.mcp.run", _boom)
    with pytest.raises(SystemExit) as exc:
        main(["--nope"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "unexpected arguments" in err
    assert "usage: agent-lsp" in err


def test_no_args_starts_server(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        "agent_lsp.server.ensure_data_dirs", lambda: called.append("dirs")
    )
    monkeypatch.setattr("agent_lsp.server.mcp.run", lambda: called.append("run"))
    main([])
    assert called == ["dirs", "run"]
