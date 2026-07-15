#!/usr/bin/env python3
"""Manually sync local git mirrors listed in infra/mirrors/mirrors.toml.

Never called by MCP / import_project — operators pull mirrors by hand, then:

  import_project(project_id="ceph", source="mirror:ceph")

Examples:

  uv run python scripts/mirror-sync.py list
  uv run python scripts/mirror-sync.py status
  uv run python scripts/mirror-sync.py sync ceph minio
  uv run python scripts/mirror-sync.py sync --tag python-build
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Allow running from repo root without install.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO / "python") not in sys.path:
    sys.path.insert(0, str(_REPO / "python"))

from agent_lsp.mirrors import (  # noqa: E402
    MirrorEntry,
    load_catalog,
    mirror_bare_path,
    mirrors_root,
    mirrors_toml_path,
)


def _git(*args: str, cwd: Path | None = None) -> None:
    cmd = ["git", *args]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def _require_git() -> None:
    if shutil.which("git") is None:
        raise SystemExit("git CLI required for mirror-sync (not found on PATH)")


def cmd_list(_: argparse.Namespace) -> int:
    cat = load_catalog()
    root = mirrors_root()
    print(f"toml: {cat.toml_path}")
    print(f"root: {root}")
    print()
    for e in cat.list():
        bare = mirror_bare_path(e.id, root)
        present = "OK" if bare.exists() else "MISSING"
        url = e.url or "(url empty — fill mirrors.toml)"
        tags = f" tags={','.join(e.tags)}" if e.tags else ""
        print(f"  {e.id:16} [{present:7}] {e.kind} depth={e.depth} ref={e.ref}{tags}")
        print(f"  {'':16}          {url}")
        if e.notes:
            print(f"  {'':16}          # {e.notes}")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    return cmd_list(_)


def _sync_one(entry: MirrorEntry, root: Path, *, force: bool) -> None:
    if not entry.syncable:
        raise SystemExit(
            f"mirror {entry.id!r}: empty url in mirrors.toml — set url= first"
        )
    root.mkdir(parents=True, exist_ok=True)
    dest = mirror_bare_path(entry.id, root)
    if force and dest.exists():
        print(f"==> remove {dest} (--force)", flush=True)
        shutil.rmtree(dest)

    if entry.kind == "mirror":
        if dest.exists():
            _git("remote", "update", "--prune", cwd=dest)
        else:
            _git("clone", "--mirror", entry.url, str(dest))
        return

    # shallow bare
    if dest.exists():
        # Update shallow tip for the configured ref.
        _git("fetch", "--depth", str(entry.depth), "origin", entry.ref, cwd=dest)
        # Point HEAD at fetched ref when possible.
        try:
            _git("symbolic-ref", "HEAD", f"refs/heads/{entry.ref}", cwd=dest)
        except subprocess.CalledProcessError:
            pass
        return

    _git(
        "clone",
        "--bare",
        "--depth",
        str(entry.depth),
        "--branch",
        entry.ref,
        entry.url,
        str(dest),
    )


def cmd_sync(args: argparse.Namespace) -> int:
    _require_git()
    cat = load_catalog()
    root = mirrors_root()
    selected: list[MirrorEntry] = []
    if args.tag:
        tag = args.tag.strip().lower()
        selected = [e for e in cat.list() if tag in {t.lower() for t in e.tags}]
        if not selected:
            raise SystemExit(f"no mirrors with tag={args.tag!r}")
    elif args.ids:
        for mid in args.ids:
            selected.append(cat.get(mid))
    else:
        selected = [e for e in cat.list() if e.syncable]

    if not selected:
        raise SystemExit("nothing to sync (all urls empty?)")

    print(f"toml: {cat.toml_path}")
    print(f"root: {root}")
    for e in selected:
        print(f"==> sync {e.id} ({e.kind}, depth={e.depth}, ref={e.ref})", flush=True)
        _sync_one(e, root, force=bool(args.force))
        bare = mirror_bare_path(e.id, root)
        print(f"    ok → {bare}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    # Ensure in-repo toml is found when run from elsewhere.
    os.environ.setdefault("AGENT_LSP_MIRRORS_TOML", str(mirrors_toml_path().resolve()))
    # Prefer repo-relative discovery when cwd is repo.
    if (Path.cwd() / "infra/mirrors/mirrors.toml").is_file():
        os.environ["AGENT_LSP_MIRRORS_TOML"] = str(
            (Path.cwd() / "infra/mirrors/mirrors.toml").resolve()
        )

    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp_list = sub.add_parser("list", help="Show catalog + present/missing")
    sp_list.set_defaults(func=cmd_list)

    sp_status = sub.add_parser("status", help="Alias for list")
    sp_status.set_defaults(func=cmd_status)

    sp_sync = sub.add_parser("sync", help="git clone/fetch into AGENT_LSP_MIRRORS")
    sp_sync.add_argument(
        "ids",
        nargs="*",
        help="Mirror ids (default: all entries with non-empty url)",
    )
    sp_sync.add_argument(
        "--tag",
        default="",
        help="Sync only mirrors with this tag (e.g. python-build)",
    )
    sp_sync.add_argument(
        "--force",
        action="store_true",
        help="Delete existing bare and re-clone",
    )
    sp_sync.set_defaults(func=cmd_sync)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
