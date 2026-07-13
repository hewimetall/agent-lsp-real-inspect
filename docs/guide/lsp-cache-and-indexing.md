# LSP cache & indexing — go / python / typescript / rust

Research note for **agent-lsp** runtimes (`agent_lsp.runtimes.RUNTIMES`).
Sources: Context7 (`/websites/go_dev_gopls`, `/golang/tools`, `/websites/rust-analyzer_github_io_book`, `/microsoft/pyright`, `/microsoft/typescript`, `/typescript-language-server/typescript-language-server`), Tavily search/extract, Searchcode on upstream repos, and local `warm_index` implementation.

**Scope:** how each language server builds an “index”, what lives in memory vs on disk, how invalidation works, and what that means for session-held containers + `warm_index`.

---

## 1. Shared model (what “indexed” means)

| Layer | Meaning | agent-lsp today |
|-------|---------|-----------------|
| **Process warm** | LSP process is up, `initialize`/`initialized` done | `ensure_runtime` |
| **Workspace graph** | Project model loaded (cargo metadata / go.mod / tsconfig / pyrightconfig) | partially via LSP progress |
| **Semantic index** | Type-checked / resolved symbols usable for refs/hover/defs | `warm_index` seed probe |
| **Disk cache** | Durable blobs surviving process restart | language-specific; **not** managed by agent-lsp yet (`AGENT_LSP_CACHE` exists but unused by LSPs) |

agent-lsp `RuntimeHub.warm()`:

1. Waits for `$/progress` `kind=end` (`LspClient.wait_until_ready`) **or**
2. Probes a seed file with `documentSymbol` (+ `references` on first symbol).

That is a **readiness heuristic**, not a guarantee that the full workspace graph is primed.

```text
ensure_runtime  →  LSP process + TCP :3737
warm_index      →  wait progress OR seed probe  →  index_status=ready
scout tools     →  assume warm session
```

---

## 2. Comparison matrix

| | **gopls** | **rust-analyzer** | **pyright** | **tsserver** (via typescript-language-server) |
|--|-----------|-------------------|-------------|-----------------------------------------------|
| **Primary unit** | Go package | Crate / `cargo metadata` package | Source file + import graph | TS `Project` (configured / inferred / external) |
| **In-memory** | Session, views, snapshots, type-checked pkgs, symbol indexes | VFS + salsa query graph + hir | `Service` → `Program` → `SourceFile` analysis state | `ProjectService` + language service programs |
| **On-disk** | `filecache` under `$GOPLSCACHE` (durable blobs); GOMODCACHE package index | Historically **no** persistent semantic cache; cargo/`target` / proc-macro artifacts | Mostly **heap**; npm wrapper may use `PYRIGHT_PYTHON_CACHE_DIR` / XDG | `.tsbuildinfo` for incremental **emit**/builder; tsserver project state is in-process |
| **Warm signal** | Implicit (requests work after load) | `warm-up-caches-on-project-load` (default true); workDoneProgress | Background analysis queue; open files prioritized | `projectLoadingStart` / `projectLoadingFinish` → LSP progress |
| **Restart cost** | Lower if `filecache` hot | High (re-prime stdlib + deps) | Medium–high (re-walk imports) | Medium (reload projects; `.tsbuildinfo` helps emit more than IDE nav) |
| **Container tip** | Persist `$GOPLSCACHE` (and module cache) | Keep **long-lived** process; volume `CARGO_HOME`/`target` | Cap heap; exclude large trees | Persist `node_modules` + `.tsbuildinfo`; raise `maxTsServerMemory` |

---

## 3. gopls (Go)

### 3.1 Architecture

Official design docs describe an in-memory **cache layer** as the core of gopls: client session, opened folders, workspace views, file snapshots (disk + unsaved overlays), memoized computations (e.g. parse `go.mod`, symbol indexes), and type-checked package results ([gopls design](https://go.dev/gopls/design/design), [implementation](https://go.dev/gopls/design/implementation)).

Early design text emphasized “rebuild on restart is OK”; the implementation later added durable helpers:

- **`filecache`** — machine-global durable blob store keyed by `(kind, sha256(recipe))`, with budget/`SetBudget`, GC, and a ~100 MB in-memory LRU in front of disk I/O ([`gopls/internal/filecache`](https://github.com/golang/tools/blob/master/gopls/internal/filecache/filecache.go)).
- **Derived indexes** — `xrefs`, `methodsets`, `typerefs` serialize type-check-derived data for faster restarts / lower RSS.
- **GOMODCACHE index** — gopls builds a persistent index of module-cache packages to speed Organize Imports / unimported completions (`importsSource`; rolled through v0.19–v0.20).

Env: **`$GOPLSCACHE`** (disk usage may exceed budget due to block rounding — noted in `filecache` docs).

### 3.2 Invalidation difficulties

Mapping **editor files** → **packages** is hard: a file can belong to multiple packages; build tags / package clause changes; external edits without `didChange` notifications ([design: cache invalidation](https://go.dev/gopls/design/design)).

### 3.3 Implications for agent-lsp

- Container image already runs `gopls serve -listen=0.0.0.0:3737`.
- Mount a volume for `$GOPLSCACHE` (and optionally module cache) across session containers to cut restart cost.
- `warm_index` seed on a `.go` file exercises package load; full module graph may still load lazily.
- gopls now ships an **experimental MCP mode** (v0.20+) — orthogonal to agent-lsp’s FastMCP scout, but relevant if we ever dual-drive gopls tools.

---

## 4. rust-analyzer (Rust)

### 4.1 Load pipeline

On start / reload ([contributing guide](https://rust-analyzer.github.io/book/contributing/guide.html)):

1. `cargo metadata` → workspace + dependency graph  
2. `rustc --print sysroot` → std / toolchain files  
3. Load into `GlobalState`; reload via `rust-analyzer/reloadWorkspace` or FS changes  

Analysis is query-based (salsa-style): indexing is **on-demand memoization**, not a single “index file”.

### 4.2 Cache priming

Config **`rust-analyzer.server.warm-up-caches-on-project-load`** (default `true`) primes caches when a project loads ([configuration book](https://rust-analyzer.github.io/book/configuration.html) / print).

Historical stance ([issue #4712](https://github.com/rust-lang/rust-analyzer/issues/4712), blog “Next Few Years”): rust-analyzer **did not persist semantic caches to disk** — each cold start reprocesses stdlib + deps (painful for short-lived editor sessions). Session-held containers are therefore the primary warm strategy.

Disk growth users notice is often **`target/`**, proc-macro dylibs, and cargo registries — not a portable “RA index” directory.

### 4.3 Implications for agent-lsp

- `warm_index` waiting on `$/progress` matches RA’s workDoneProgress during load/prime.
- Prefer **one long-lived container per session** (ADR-0007); killing the process throws away salsa state.
- Volume-mount `CARGO_HOME` / shared `target` for the worktree to reduce cargo metadata + build script churn.
- Seed probe on `lib.rs`/`main.rs` after progress end is a good second gate (already done).

---

## 5. Pyright (Python)

### 5.1 Program model

From [Pyright internals](https://github.com/microsoft/pyright/blob/main/docs/internals.md):

- **`Service`** — persistent in-memory controller (one per multi-root workspace folder).
- **`Program`** — config + set of source files; FS watchers; prioritizes **open files** and their import dependencies.
- A file enters the program if: listed by config, **open in the editor**, or imported (transitively).
- **`ImportResolver`** builds the module graph.
- Per-file **`SourceFile`** holds analysis phase state + diagnostics.

### 5.2 Caching

- **`CacheManager`** ([`cacheManager.ts`](https://github.com/microsoft/pyright/blob/main/packages/pyright-internal/src/analyzer/cacheManager.ts)): tracks registered `CacheOwner`s, watches heap / worker SharedArrayBuffer usage, **`emptyCache()`** under memory pressure — this is **eviction**, not a durable index.
- **`parentDirectoryCache`**, **`cellChainIndex`** (notebooks), background analysis workers (`BackgroundAnalysis*`) keep analysis responsive without blocking the LSP thread.
- The **`pyright` npm/Python wrapper** may resolve a cache dir via `PYRIGHT_PYTHON_CACHE_DIR` or `XDG_CACHE_HOME` (install/metadata — not the same as the type-checker’s semantic DB).

There is **no durable cross-process symbol DB** comparable to gopls `filecache` for hover/refs.

### 5.3 Implications for agent-lsp

- Warmth ≈ “program contains enough of the import graph”. Seed `didOpen` + `documentSymbol` pulls the seed and dependencies into the program — aligns with current `warm_index`.
- Large monorepos: configure `include`/`exclude` (pyrightconfig / pyproject) or indexing stays cold for a long time.
- Container: bound Node heap; optional `PYRIGHT_PYTHON_CACHE_DIR` on a volume if using the Python wrapper’s download cache.

---

## 6. TypeScript — tsserver + typescript-language-server

### 6.1 Split responsibility

| Component | Role |
|-----------|------|
| **typescript-language-server** | Thin LSP façade over VS Code’s TS language features / tsserver |
| **tsserver** | JSON-RPC on stdio; owns **ProjectService**, configured / inferred / external projects |

TLS reports project load via **`projectLoadingStart` / `projectLoadingFinish`**, mapped to LSP **`window/workDoneProgress`** (`ServerInitializingIndicator` in typescript-language-server). That is the natural signal for agent-lsp’s `$/progress` waiter.

Init knobs include `maxTsServerMemory`, `tsserver.useSyntaxServer`, log verbosity ([TLS init docs](https://github.com/typescript-language-server/typescript-language-server)).

### 6.2 Caching / incremental state

- **In-process:** `ProjectService` keeps ScriptInfo / projects / language service state for the life of tsserver.
- **On-disk incremental:** compiler **`incremental` / `composite`** + **`.tsbuildinfo`** (`tsBuildInfoFile`) speed **rebuild/emit** and builder programs ([Compiler API watch/builder](https://github.com/microsoft/TypeScript/wiki/Using-the-Compiler-API)). This helps tsserver when projects are builder-backed, but IDE navigation still pays project-graph load cost on cold start.
- **Inferred projects** (no/nearby `tsconfig.json`) are weaker and can thrash; prefer a real `tsconfig.json` in scout workspaces.

### 6.3 Implications for agent-lsp

- Image ENTRYPOINT bridges stdio TLS → TCP `:3737`; Cmd remains `typescript-language-server --stdio`.
- Pass through init options for memory on large repos.
- Persist `node_modules` + `.tsbuildinfo` in the worktree volume; do not expect a separate global “tsserver cache” directory.
- `warm_index` should wait for projectLoadingFinish (progress end) then seed-open a `.ts`/`.tsx` file.

---

## 7. agent-lsp integration map

| Runtime knob | go | rust | python | typescript |
|--------------|----|------|--------|------------|
| Image | `agent-lsp-go` | `agent-lsp-rust` | `agent-lsp-python` | `agent-lsp-typescript` |
| Transport | native TCP | bridge | bridge | bridge |
| Progress | optional | strong (prime) | weak/partial | strong (projectLoading*) |
| Disk volume worth mounting | `$GOPLSCACHE`, module cache | `CARGO_HOME`, `target` | optional wrapper cache | `node_modules`, `.tsbuildinfo` |
| Seed glob | `**/*.go` | `**/lib.rs`, `**/main.rs` | `**/*.py` | `**/*.{ts,tsx}` |

### Gaps / follow-ups

1. **`AGENT_LSP_CACHE`** is created but not wired to `$GOPLSCACHE` / cargo / tsbuildinfo paths — candidates for `ensure_runtime` env injection.
2. **Warm readiness** treats seed probe success as full index; for RA/TS, prefer requiring progress-end **and** probe.
3. **Per-language init options** (RA `warm-up-caches-on-project-load`, TLS `maxTsServerMemory`, gopls `importsSource`) are not yet passed from MCP tool args.
4. **Container reuse** across checkouts of the same `project_id` could keep disk caches hot even when worktrees change (bind new worktree, keep cache volumes).

---

## 8. Source index (research session)

| Kind | ID / URL |
|------|----------|
| Context7 | `/websites/go_dev_gopls`, `/golang/tools`, `/websites/rust-analyzer_github_io_book`, `/microsoft/pyright`, `/microsoft/typescript`, `/typescript-language-server/typescript-language-server` |
| Upstream code | `golang/tools` `gopls/internal/filecache/filecache.go`; `microsoft/pyright` `cacheManager.ts`; `microsoft/TypeScript` `src/server/*` |
| Issues / book | [RA #4712 Persistent caches](https://github.com/rust-lang/rust-analyzer/issues/4712); [RA configuration](https://rust-analyzer.github.io/book/configuration.html); [gopls design](https://go.dev/gopls/design/design) |
| Local | `python/agent_lsp/runtime_hub.py` (`warm`), `python/agent_lsp/lsp_client.py` (`$/progress`), `python/agent_lsp/runtimes.py` |

---

## 9. Related docs

- [ADR-0007 session-held containers](../adr/0007-session-held-containers.md)
- [ADR-0009 cache volumes & warm_index policy](../adr/0009-lsp-cache-volumes-and-warm-index.md) *(decision distilled from this research)*
- [guide/tasks.md](tasks.md) — `warm_index` requires `task=True`
- [infra/docker/lsp/README.md](../../infra/docker/lsp/README.md) — runtime images
