"""Minimal import/CLI smoke check for the published single wheel / sdist.

Used by ``.github/workflows/release.yml`` via::

    uv run --isolated --no-project --with dist/*.whl tests/smoke_pypi.py
"""

from __future__ import annotations


def main() -> None:
    import agent_lsp
    from agent_lsp.server import main as server_main

    assert callable(server_main)
    ver = getattr(agent_lsp, "__version__", None)
    assert isinstance(ver, str) and ver and ver not in {"?", "0.0.0+unknown"}, ver
    # One wheel must expose all native types.
    from agent_lsp._tasks import DockerService, GitService, StateStore, TaskStore

    assert TaskStore is not None
    assert StateStore is not None
    assert GitService is not None
    assert DockerService is not None
    assert agent_lsp.TaskStore is TaskStore
    assert agent_lsp.StateStore is StateStore
    assert agent_lsp.GitService is GitService
    assert agent_lsp.DockerService is DockerService

    print(f"smoke_ok agent_lsp={ver} (single-wheel)")


if __name__ == "__main__":
    main()
