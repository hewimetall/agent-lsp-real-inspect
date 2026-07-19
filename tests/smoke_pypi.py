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
    # Native extensions (tasks + state/git/docker) must load from ONE wheel.
    from agent_lsp._tasks import DockerService, GitService, StateStore, TaskStore

    assert TaskStore is not None
    assert StateStore is not None
    assert GitService is not None
    assert DockerService is not None
    import agent_lsp_docker  # noqa: F401
    import agent_lsp_git  # noqa: F401
    import agent_lsp_state  # noqa: F401
    from agent_lsp_docker import DockerService as DS
    from agent_lsp_git import GitService as GS
    from agent_lsp_state import StateStore as SS

    assert SS is StateStore
    assert GS is GitService
    assert DS is DockerService

    print(f"smoke_ok agent_lsp={ver} (single-wheel)")


if __name__ == "__main__":
    main()
