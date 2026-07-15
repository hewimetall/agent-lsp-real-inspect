"""Local git mirrors — catalog in mirrors.toml, sync by hand, resolve for import."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from agent_lsp import paths as paths_mod
from agent_lsp.paths import require_id

# Repo-relative default; override with AGENT_LSP_MIRRORS_TOML.
_DEFAULT_TOML_CANDIDATES = (
    Path("infra/mirrors/mirrors.toml"),
    Path("/opt/agent-lsp/infra/mirrors/mirrors.toml"),
    Path("/etc/agent-lsp/mirrors.toml"),
)


@dataclass(frozen=True)
class MirrorEntry:
    id: str
    url: str
    ref: str = "main"
    depth: int = 1
    kind: str = "shallow"  # shallow | mirror
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def syncable(self) -> bool:
        return bool(self.url.strip())


@dataclass(frozen=True)
class MirrorCatalog:
    entries: dict[str, MirrorEntry]
    toml_path: Path

    def get(self, mirror_id: str) -> MirrorEntry:
        key = require_id(mirror_id.strip(), "mirror_id").lower()
        if key not in self.entries:
            known = ", ".join(sorted(self.entries)) or "(empty)"
            raise KeyError(f"unknown mirror {mirror_id!r}; known: {known}")
        return self.entries[key]

    def list(self) -> list[MirrorEntry]:
        return [self.entries[k] for k in sorted(self.entries)]


def mirrors_root() -> Path:
    """Bare clones live here: ``<id>.git`` — same rule as ``paths.mirrors_dir``."""
    return paths_mod.mirrors_dir()


def mirrors_toml_path(*, prefer: Path | None = None) -> Path:
    override = (os.environ.get("AGENT_LSP_MIRRORS_TOML") or "").strip()
    if override:
        return Path(override)
    if prefer is not None and prefer.is_file():
        return prefer
    for cand in _DEFAULT_TOML_CANDIDATES:
        if cand.is_file():
            return cand
    # Prefer in-repo path even if missing (clearer errors).
    return prefer or _DEFAULT_TOML_CANDIDATES[0]


def mirror_bare_path(mirror_id: str, root: Path | None = None) -> Path:
    mid = require_id(mirror_id, "mirror_id")
    return (root or mirrors_root()) / f"{mid}.git"


def load_catalog(toml_path: Path | None = None) -> MirrorCatalog:
    path = toml_path or mirrors_toml_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"mirrors.toml not found at {path}; set AGENT_LSP_MIRRORS_TOML or add "
            "infra/mirrors/mirrors.toml"
        )
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    raw_list = data.get("mirror") or data.get("mirrors") or []
    if isinstance(raw_list, dict):
        # Allow [mirrors.ceph] style accidentally — reject clearly.
        raise ValueError(
            "mirrors.toml: expected [[mirror]] array, not a [mirrors] table of entries"
        )
    entries: dict[str, MirrorEntry] = {}
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or "").strip()
        if not mid:
            continue
        mid = require_id(mid, "mirror_id")
        tags_raw = item.get("tags") or []
        tags = tuple(str(t) for t in tags_raw) if isinstance(tags_raw, list) else ()
        depth = int(item.get("depth") or 1)
        if depth < 1:
            depth = 1
        kind = str(item.get("kind") or "shallow").strip().lower()
        if kind not in {"shallow", "mirror"}:
            kind = "shallow"
        entry = MirrorEntry(
            id=mid,
            url=str(item.get("url") or "").strip(),
            ref=str(item.get("ref") or "main").strip() or "main",
            depth=depth,
            kind=kind,
            notes=str(item.get("notes") or "").strip(),
            tags=tags,
        )
        entries[mid.lower()] = entry
    return MirrorCatalog(entries=entries, toml_path=path)


def parse_mirror_source(source: str) -> str | None:
    """Return mirror id if ``source`` is ``mirror:id`` / ``mirror://id``.

    Returns ``None`` for non-mirror sources. Raises ``ValueError`` for the
    mirror prefix with an empty id (``mirror:`` / ``mirror://``) so callers
    fail closed instead of treating it as a remote URL.
    """
    s = (source or "").strip()
    if not s:
        return None
    lower = s.lower()
    if lower.startswith("mirror://"):
        mid = s[len("mirror://") :].strip().strip("/")
        if not mid:
            raise ValueError("empty mirror id (expected mirror://<id>)")
        return mid
    if lower.startswith("mirror:"):
        mid = s[len("mirror:") :].strip().strip("/")
        if not mid:
            raise ValueError("empty mirror id (expected mirror:<id>)")
        return mid
    return None


def resolve_source(source: str) -> Path | str:
    """Map import source to a local path or leave remote URL unchanged.

    ``mirror:ceph`` → absolute path to synced bare (raises if missing / unknown).
    Existing filesystem paths and git URLs pass through.
    """
    mid = parse_mirror_source(source)
    if mid is None:
        return source
    # Validate id shape before catalog lookup / path assembly.
    require_id(mid.strip(), "mirror_id")
    catalog = load_catalog()
    entry = catalog.get(mid)
    if not entry.syncable:
        raise FileNotFoundError(
            f"mirror {entry.id!r} has empty url in {catalog.toml_path}; "
            "set url= then run: uv run python scripts/mirror-sync.py sync "
            f"{entry.id}"
        )
    root = mirrors_root()
    bare = mirror_bare_path(entry.id, root)
    if not bare.exists():
        raise FileNotFoundError(
            f"mirror {entry.id!r} not synced at {bare}; "
            f"run: uv run python scripts/mirror-sync.py sync {entry.id}"
        )
    resolved = bare.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(
            f"mirror bare escapes mirrors root: {resolved} (root={root_resolved})"
        ) from exc
    return resolved
