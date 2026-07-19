"""Minimal import/CLI smoke check for published wheels / sdists.

Used by ``.github/workflows/release.yml`` via::

    uv run --isolated --no-project --with dist/*.whl tests/smoke_pypi.py
"""

from __future__ import annotations


def main() -> None:
    import agent_lsp
    from agent_lsp.server import main as server_main

    assert callable(server_main)
    # Native TaskStore extension must load from the wheel.
    from agent_lsp._tasks import TaskStore

    assert TaskStore is not None
    import agent_lsp_state  # noqa: F401
    import agent_lsp_git  # noqa: F401
    import agent_lsp_docker  # noqa: F401

    print(f"smoke_ok agent_lsp={getattr(agent_lsp, '__version__', '?')}")


if __name__ == "__main__":
    main()
