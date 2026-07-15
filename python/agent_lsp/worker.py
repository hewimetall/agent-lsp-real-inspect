"""Background scout worker: claim_next → import / ensure / deps / warm."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, cast

from agent_lsp._tasks import TaskStore

logger = logging.getLogger(__name__)

POLL_SECONDS = float(os.environ.get("AGENT_LSP_WORKER_POLL_SECONDS", "0.5"))
SCOUT_TARGETS = frozenset(
    {
        "import_project",
        "ensure_runtime",
        "warm_index",
        "install_workspace_deps",
        "install_apt_packages",
    }
)


def _as_task(row: object) -> dict[str, Any]:
    return cast(dict[str, Any], dict(row))  # type: ignore[arg-type]


class ScoutWorker:
    """Poll TaskStore and run long scout pipeline steps."""

    def __init__(self, tasks: TaskStore, *, poll_seconds: float = POLL_SECONDS) -> None:
        self._tasks = tasks
        self._poll = poll_seconds
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def wake(self) -> None:
        self._wake.set()

    def start_daemon(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        try:
            self._tasks.reclaim_stale(0)
        except Exception:
            logger.exception("reclaim_stale on boot failed")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="agent-lsp-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def process_one(self) -> bool:
        claimed = self._tasks.claim_next()
        if claimed is None:
            return False
        task = _as_task(claimed)
        self._run_task(task)
        return True

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.process_one()
            except Exception:
                logger.exception("worker iteration failed")
                worked = False
            if worked:
                continue
            self._wake.wait(timeout=self._poll)
            self._wake.clear()

    def _payload(self, task: dict[str, Any]) -> dict[str, Any]:
        raw = task.get("artifact") or "{}"
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _run_task(self, task: dict[str, Any]) -> None:
        tid = task["task_id"]
        target = task["target"]
        if target not in SCOUT_TARGETS:
            self._tasks.update(tid, status="error", error=f"unsupported target: {target}")
            return
        try:
            if target == "import_project":
                self._import_project(tid, task)
            elif target == "ensure_runtime":
                self._ensure_runtime(tid, task)
            elif target == "install_workspace_deps":
                self._install_workspace_deps(tid, task)
            elif target == "install_apt_packages":
                self._install_apt_packages(tid, task)
            else:
                self._warm_index(tid, task)
        except Exception as exc:  # noqa: BLE001
            logger.exception("task %s failed", tid)
            self._tasks.update(tid, status="error", error=str(exc))

    def _import_project(self, tid: str, task: dict[str, Any]) -> None:
        from agent_lsp.mirrors import resolve_source
        from agent_lsp.paths import project_bare_path
        from agent_lsp_git import GitService

        payload = self._payload(task)
        project_id = str(payload.get("project_id") or "")
        source = str(payload.get("source") or "")
        if not project_id or not source:
            self._tasks.update(tid, status="error", error="missing project_id/source")
            return
        bare = project_bare_path(project_id)
        if bare.exists():
            self._tasks.update(tid, status="error", error=f"project_exists: {project_id}")
            return
        try:
            resolved = resolve_source(source)
        except (FileNotFoundError, KeyError, ValueError) as exc:
            self._tasks.update(tid, status="error", error=str(exc))
            return
        git = GitService()
        src = Path(str(resolved))
        if src.exists():
            path = git.import_local(str(src.resolve()), str(bare))
            origin = f"mirror→{src}" if str(resolved) != source else str(src)
        else:
            path = git.clone_bare(str(resolved), str(bare))
            origin = str(resolved)
        result = json.dumps(
            {
                "project_id": project_id,
                "bare": path,
                "source": source,
                "resolved_source": origin,
            }
        )
        self._tasks.update(tid, status="done", artifact=result, logs="import_project ok")

    def _ensure_runtime(self, tid: str, task: dict[str, Any]) -> None:
        from agent_lsp import server
        from agent_lsp.runtime_hub import HUB, allow_local_runtime
        from agent_lsp.runtimes import resolve_image

        payload = self._payload(task)
        session_id = str(task.get("session_id") or "")
        language = str(payload.get("language") or "")
        prefer_container = bool(payload.get("prefer_container", True))
        language_version = str(payload.get("language_version") or "")
        image = str(payload.get("image") or "")
        if not session_id or not language:
            self._tasks.update(tid, status="error", error="missing session_id/language")
            return
        bound = server._active_workspace(session_id)
        if isinstance(bound, dict):
            self._tasks.update(tid, status="error", error=json.dumps(bound))
            return
        _, ws = bound
        workspace = Path(ws["path"])
        docker = server.get_docker()
        resolved = resolve_image(language, language_version, image)
        # Production path is Docker-only. Local LSP requires AGENT_LSP_ALLOW_LOCAL=1
        # and an explicit prefer_container=false (tests/dev).
        use_local = (not prefer_container) and allow_local_runtime()
        if use_local:
            try:
                rt = HUB.ensure_local(
                    session_id,
                    workspace,
                    language,
                    docker=docker,
                    language_version=language_version,
                )
            except Exception as exc:
                self._tasks.update(tid, status="error", error=str(exc))
                return
        else:
            if docker is None:
                self._tasks.update(
                    tid,
                    status="error",
                    error=(
                        "Docker unavailable — LSP runtimes require containers "
                        "(fix get_docker / docker.sock). Local fallback is disabled."
                    ),
                )
                return
            try:
                rt = HUB.ensure_container(
                    session_id,
                    workspace,
                    language,
                    docker,
                    image_override=resolved,
                    language_version=language_version,
                )
            except Exception as exc:
                self._tasks.update(
                    tid,
                    status="error",
                    error=f"container runtime failed (no local fallback): {exc}",
                )
                return
        server.get_state().bind_container(
            session_id,
            rt.container_id or "unknown",
            image=rt.image or resolved,
            language=language,
            host_port=rt.host_port,
            runtime_mode=rt.runtime_mode,
        )
        server.get_state().set_index_status(session_id, "warming")
        result = {
            "session_id": session_id,
            "language": language,
            "language_version": language_version or None,
            "image": rt.image or resolved,
            "runtime_mode": rt.runtime_mode,
            "container_id": rt.container_id,
            "host_port": rt.host_port,
            "index_status": "warming",
        }
        self._tasks.update(tid, status="done", artifact=json.dumps(result))

    def _run_script(
        self,
        *,
        workspace: Path,
        image: str,
        script: str,
        env: list[str] | None = None,
        binds: list[str] | None = None,
    ) -> dict[str, Any]:
        from agent_lsp import server

        docker = server.get_docker()
        cmd = ["bash", "-lc", script]
        if docker is None:
            from agent_lsp.runtime_hub import allow_local_runtime

            if not allow_local_runtime():
                return {
                    "mode": "error",
                    "image": image,
                    "status_code": 1,
                    "logs": (
                        "Docker unavailable — install/deps scripts require containers "
                        "(AGENT_LSP_ALLOW_LOCAL=1 to run on host for tests)"
                    ),
                    "container_id": None,
                }
            completed = subprocess.run(
                cmd,
                cwd=str(workspace),
                capture_output=True,
                text=True,
                check=False,
            )
            logs = (completed.stdout or "") + (completed.stderr or "")
            return {
                "mode": "local",
                "image": None,
                "status_code": completed.returncode,
                "logs": logs[-8000:],
                "container_id": None,
            }
        result = docker.run(
            image,
            cmd,
            binds=binds or [f"{workspace.resolve()}:/workspace:rw"],
            workdir="/workspace",
            env=env or [],
            auto_remove=True,
        )
        return {
            "mode": "container",
            "image": image,
            "status_code": result.get("status_code"),
            "logs": (result.get("logs") or "")[-8000:],
            "container_id": result.get("container_id"),
        }

    def _install_workspace_deps(self, tid: str, task: dict[str, Any]) -> None:
        from agent_lsp import env_layout, server
        from agent_lsp.deps import build_deps_plan
        from agent_lsp.runtime_hub import HUB

        payload = self._payload(task)
        session_id = str(task.get("session_id") or "")
        if not session_id:
            self._tasks.update(tid, status="error", error="missing session_id")
            return
        bound = server._active_workspace(session_id)
        if isinstance(bound, dict):
            self._tasks.update(tid, status="error", error=json.dumps(bound))
            return
        _, ws = bound
        workspace = Path(ws["path"])
        rt = HUB.get(session_id)
        language = str(payload.get("language") or (rt.language if rt else "") or "")
        language_version = str(
            payload.get("language_version")
            or (rt.language_version if rt else "")
            or ""
        )
        if not language:
            self._tasks.update(
                tid,
                status="error",
                error="missing language (pass language= or call ensure_runtime first)",
            )
            return
        packages = payload.get("packages") or []
        apt_packages = payload.get("apt_packages") or []
        if not isinstance(packages, list):
            packages = []
        if not isinstance(apt_packages, list):
            apt_packages = []
        extra_args = payload.get("extra_args") or []
        if not isinstance(extra_args, list):
            extra_args = []
        manager = str(payload.get("manager") or "auto")
        restart_runtime = bool(payload.get("restart_runtime", True))

        env_layout.ensure_agent_lsp_dir(workspace)
        plan = build_deps_plan(
            workspace,
            language,
            language_version=language_version,
            manager=manager,
            packages=[str(p) for p in packages],
            apt_packages=[str(p) for p in apt_packages],
            extra_args=[str(a) for a in extra_args],
            install_image=str(payload.get("install_image") or ""),
        )
        binds = [f"{workspace.resolve()}:/workspace:rw"]
        env: list[str] = []
        if plan.language == "go":
            mod = env_layout.go_modcache_host(session_id)
            mod.mkdir(parents=True, exist_ok=True)
            binds.append(f"{mod.resolve()}:/go/pkg/mod:rw")
            env.extend(["GOPATH=/go", "GOMODCACHE=/go/pkg/mod"])
        elif plan.language == "python":
            pip = env_layout.pip_cache_host(session_id)
            pip.mkdir(parents=True, exist_ok=True)
            binds.append(f"{pip.resolve()}:/cache/pip:rw")
            env.append("PIP_CACHE_DIR=/cache/pip")
        elif plan.language == "typescript":
            npm = env_layout.npm_cache_host(session_id)
            npm.mkdir(parents=True, exist_ok=True)
            binds.append(f"{npm.resolve()}:/cache/npm:rw")
            env.append("npm_config_cache=/cache/npm")

        run = self._run_script(
            workspace=workspace,
            image=plan.install_image,
            script=plan.script,
            env=env,
            binds=binds,
        )
        status_code = run.get("status_code")
        ok = status_code is not None and int(status_code) == 0
        site = [str(p) for p in env_layout.discover_site_packages(workspace)]
        artifact = {
            "session_id": session_id,
            "language": plan.language,
            "language_version": plan.language_version or None,
            "manager": plan.manager,
            "packages": list(plan.packages),
            "apt_packages": list(plan.apt_packages),
            "install_image": plan.install_image,
            "site_packages": site,
            "venv": str(env_layout.venv_path(workspace)) if plan.language == "python" else None,
            "node_modules": str(env_layout.node_modules_path(workspace))
            if plan.language == "typescript"
            else None,
            "run": run,
            "restarted_runtime": False,
        }
        if not ok:
            self._tasks.update(
                tid,
                status="error",
                artifact=json.dumps(artifact),
                error=f"install failed status_code={run.get('status_code')}",
                logs=str(run.get("logs") or "")[-4000:],
            )
            return

        if restart_runtime and rt is not None:
            from agent_lsp.runtime_hub import allow_local_runtime

            docker = server.get_docker()
            was_container = rt.runtime_mode == "container"
            lang = rt.language
            ver = rt.language_version
            image = rt.image
            # force=True: recycle even when language/image match so new deps load.
            # ensure_* starts the replacement first; put() tears down the old runtime.
            if was_container or not allow_local_runtime():
                if docker is None:
                    self._tasks.update(
                        tid,
                        status="error",
                        artifact=json.dumps(artifact),
                        error="Docker unavailable for runtime restart (no local fallback)",
                    )
                    return
                try:
                    HUB.ensure_container(
                        session_id,
                        workspace,
                        lang,
                        docker,
                        image_override=image,
                        language_version=ver,
                        force=True,
                    )
                except Exception as exc:
                    # Keep previous container, but mark stale so the next ensure_*
                    # recycles instead of reusing an LSP that missed the new deps.
                    stale = HUB.get(session_id)
                    if stale is not None:
                        stale.needs_recycle = True
                        stale.index_status = "cold"
                        stale.error = f"recycle after deps failed: {exc}"
                    try:
                        server.get_state().set_index_status(session_id, "cold")
                    except Exception:
                        pass
                    self._tasks.update(
                        tid,
                        status="error",
                        artifact=json.dumps(artifact),
                        error=f"container restart failed (previous runtime kept, needs_recycle): {exc}",
                    )
                    return
            else:
                HUB.ensure_local(
                    session_id,
                    workspace,
                    lang,
                    docker=docker,
                    language_version=ver,
                    force=True,
                )
            artifact["restarted_runtime"] = True
            server.get_state().set_index_status(session_id, "cold")
        elif rt is not None:
            HUB.refresh_settings(session_id)

        self._tasks.update(
            tid,
            status="done",
            artifact=json.dumps(artifact),
            logs=str(run.get("logs") or "")[-4000:],
        )

    def _install_apt_packages(self, tid: str, task: dict[str, Any]) -> None:
        from agent_lsp import env_layout, server
        from agent_lsp.deps import build_apt_only_script
        from agent_lsp.runtime_hub import HUB
        from agent_lsp.runtimes import resolve_install_image

        payload = self._payload(task)
        session_id = str(task.get("session_id") or "")
        packages = payload.get("packages") or []
        if not session_id:
            self._tasks.update(tid, status="error", error="missing session_id")
            return
        if not isinstance(packages, list) or not packages:
            self._tasks.update(tid, status="error", error="packages must be a non-empty list")
            return
        bound = server._active_workspace(session_id)
        if isinstance(bound, dict):
            self._tasks.update(tid, status="error", error=json.dumps(bound))
            return
        _, ws = bound
        workspace = Path(ws["path"])
        rt = HUB.get(session_id)
        language = str(payload.get("language") or (rt.language if rt else "python") or "python")
        language_version = str(
            payload.get("language_version") or (rt.language_version if rt else "") or ""
        )
        # Persist list for later install_workspace_deps (no allowlist validation).
        merged = env_layout.append_apt_packages(workspace, [str(p) for p in packages])
        script = build_apt_only_script(merged)
        image = str(payload.get("install_image") or "") or resolve_install_image(
            language, language_version
        )
        run = self._run_script(
            workspace=workspace,
            image=image,
            script=script,
            binds=[f"{workspace.resolve()}:/workspace:rw"],
        )
        artifact = {
            "session_id": session_id,
            "packages": merged,
            "install_image": image,
            "note": (
                "apt packages are installed in a throwaway container for bootstrap; "
                "the list is persisted in .agent-lsp/apt-packages.txt and reapplied "
                "on install_workspace_deps"
            ),
            "apt_packages_file": str(env_layout.apt_packages_file(workspace)),
            "run": run,
        }
        status_code = run.get("status_code")
        ok = status_code is not None and int(status_code) == 0
        if ok:
            self._tasks.update(
                tid,
                status="done",
                artifact=json.dumps(artifact),
                logs=str(run.get("logs") or "")[-4000:],
            )
        else:
            self._tasks.update(
                tid,
                status="error",
                artifact=json.dumps(artifact),
                error=f"apt install failed status_code={run.get('status_code')}",
                logs=str(run.get("logs") or "")[-4000:],
            )

    def _warm_index(self, tid: str, task: dict[str, Any]) -> None:
        from agent_lsp import server
        from agent_lsp.runtime_hub import HUB

        payload = self._payload(task)
        session_id = str(task.get("session_id") or "")
        timeout = float(payload.get("timeout_seconds") or 120.0)
        if not session_id:
            self._tasks.update(tid, status="error", error="missing session_id")
            return
        rt = HUB.warm(session_id, timeout=timeout)
        server.get_state().set_index_status(session_id, rt.index_status)
        indexed = rt.index_status == "ready"
        result = {
            "session_id": session_id,
            "index_status": rt.index_status,
            "indexed": indexed,
            "language": rt.language,
            "language_version": rt.language_version or None,
            "runtime_mode": rt.runtime_mode,
            "error": rt.error,
        }
        if indexed:
            self._tasks.update(tid, status="done", artifact=json.dumps(result))
        else:
            self._tasks.update(
                tid,
                status="error",
                artifact=json.dumps(result),
                error=rt.error or "index warm failed",
            )


_worker: ScoutWorker | None = None
_worker_lock = threading.Lock()


def wake_worker(tasks: TaskStore) -> ScoutWorker:
    """Ensure a daemon worker is running and wake it."""
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = ScoutWorker(tasks)
            _worker.start_daemon()
        else:
            _worker._tasks = tasks
        _worker.wake()
        return _worker
