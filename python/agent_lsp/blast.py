"""blast_radius — signature scout tool.

Given changed files, enumerate exported symbols, resolve references in parallel,
partition test vs non-test callers.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from agent_lsp.lsp_client import LspClient, SymbolInfo
from agent_lsp.paths import resolve_under_root


def is_test_file(path: str) -> bool:
    p = path.replace("\\", "/")
    base = Path(p).name
    if base.endswith("_test.go"):
        return True
    if ".test." in base or ".spec." in base:
        return True
    if base.startswith("test_"):
        return True
    return False


def uri_to_path(uri: str) -> str:
    """Decode file:// URI to a filesystem path."""
    if uri.startswith("file://"):
        parsed = urlparse(uri)
        return unquote(parsed.path)
    return unquote(uri)


# LSP SymbolKind: 5=class, 6=method, 12=function, 13=variable, 14=constant, ...
_EXPORTED_KINDS = {5, 6, 10, 11, 12, 13, 14, 23, 26}


def _looks_exported(sym: SymbolInfo, language: str) -> bool:
    name = sym.name.rsplit(".", 1)[-1]
    if not name:
        return False
    if language in {"go", "rust"}:
        return name[0].isupper()
    if name.startswith("_"):
        return False
    return sym.kind in _EXPORTED_KINDS


@dataclass
class CallerRef:
    file: str
    line: int
    character: int


@dataclass
class BlastSymbol:
    name: str
    file: str
    line: int
    non_test_callers: list[CallerRef] = field(default_factory=list)
    test_callers: list[CallerRef] = field(default_factory=list)
    warning: str | None = None


@dataclass
class BlastResult:
    symbols: list[BlastSymbol]
    changed_files: list[str]
    indexed: bool


def blast_radius(
    client: LspClient,
    changed_files: list[str],
    *,
    include_transitive: bool = False,
    max_workers: int = 8,
) -> BlastResult:
    root = client.root
    symbols: list[SymbolInfo] = []
    for rel in changed_files:
        try:
            full = resolve_under_root(root, rel)
        except ValueError:
            continue
        if not full.is_file():
            continue
        for sym in client.document_symbols(full):
            if _looks_exported(sym, client.language_id):
                symbols.append(sym)

    # Warm references once on first symbol if present.
    if symbols:
        try:
            client.references(symbols[0].file, symbols[0].line, symbols[0].character)
        except Exception:
            pass

    results: list[BlastSymbol] = []

    def query_one(sym: SymbolInfo) -> BlastSymbol:
        item = BlastSymbol(name=sym.name, file=sym.file, line=sym.line)
        try:
            locs = client.references(sym.file, sym.line, sym.character, include_declaration=False)
        except Exception as exc:  # noqa: BLE001
            item.warning = str(exc)
            return item
        for loc in locs:
            file_path = uri_to_path(loc.uri)
            ref = CallerRef(file=file_path, line=loc.line, character=loc.character)
            if is_test_file(file_path):
                item.test_callers.append(ref)
            else:
                if file_path == sym.file and loc.line == sym.line:
                    continue
                item.non_test_callers.append(ref)
        return item

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = [pool.submit(query_one, s) for s in symbols]
        for fut in as_completed(futs):
            results.append(fut.result())

    if include_transitive:
        extra: list[BlastSymbol] = []
        for item in list(results):
            for caller in item.non_test_callers[:16]:
                try:
                    hover = client.hover(caller.file, caller.line, caller.character)
                    name = (
                        hover.split("\n", 1)[0][:80]
                        or f"{Path(caller.file).name}:{caller.line}"
                    )
                    hop = BlastSymbol(name=f"→{name}", file=caller.file, line=caller.line)
                    for loc in client.references(caller.file, caller.line, caller.character):
                        fp = uri_to_path(loc.uri)
                        ref = CallerRef(file=fp, line=loc.line, character=loc.character)
                        if is_test_file(fp):
                            hop.test_callers.append(ref)
                        else:
                            hop.non_test_callers.append(ref)
                    extra.append(hop)
                except Exception:
                    continue
        results.extend(extra)

    return BlastResult(
        symbols=results,
        changed_files=changed_files,
        indexed=client.is_workspace_loaded(),
    )


def blast_to_dict(result: BlastResult) -> dict[str, Any]:
    return {
        "changed_files": result.changed_files,
        "indexed": result.indexed,
        "symbols": [
            {
                "name": s.name,
                "file": s.file,
                "line": s.line,
                "non_test_callers": [asdict(c) for c in s.non_test_callers],
                "test_callers": [asdict(c) for c in s.test_callers],
                "warning": s.warning,
            }
            for s in result.symbols
        ],
    }
