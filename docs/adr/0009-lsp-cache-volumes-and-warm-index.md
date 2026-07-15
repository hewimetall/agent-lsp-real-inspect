# ADR-0009: LSP cache volumes and warm_index readiness

- Status: Accepted
- Date: 2026-07-13
- Code: D6
- Deciders: architecture (from cache/indexing research)

## Context

agent-lsp holds language servers in long-lived session containers (ADR-0007) and
exposes `warm_index` as a task-required gate before scout tools. The four
supported servers (**gopls**, **rust-analyzer**, **pyright**,
**typescript-language-server/tsserver**) differ sharply in whether semantic
state survives process restart and what “indexed” means.

Research: [`docs/guide/lsp-cache-and-indexing.md`](../guide/lsp-cache-and-indexing.md).

Without an explicit policy we under-use disk caches (especially gopls
`$GOPLSCACHE`) and over-claim readiness when a seed probe succeeds before
project load finishes.

## Decision

1. **Session-held process is the primary warm cache** for all registered languages
   (go / python / typescript / rust / cpp).
   Do not restart the LSP between scout calls in one session.

2. **Language-specific durable volumes** (when using containers) SHOULD be
   bind-mounted beside the worktree:
   - go: `$GOPLSCACHE` (+ module cache if practical)
   - rust: `CARGO_HOME` / shared cargo target where safe
   - typescript: retain worktree `node_modules` + `.tsbuildinfo`
   - python: optional wrapper cache dir; rely on in-process `Program` otherwise

3. **`warm_index` readiness policy** (target behavior):
   - Prefer LSP **workDoneProgress end** (TS projectLoading*, RA prime) when the
     server emits it.
   - Always run a **seed-file probe** (`documentSymbol`, optional `references`).
   - Mark `ready` only if **progress-end OR (for servers without progress)
     probe success**; prefer **progress-end AND probe** for rust + typescript
     when both are available.

4. **`AGENT_LSP_CACHE`** is the host-side root for injecting per-session cache
   directories into container env (e.g. `GOPLSCACHE=$AGENT_LSP_CACHE/gopls/<id>`).
   Implementation may land incrementally; the contract is fixed here.

## Consequences

### Positive

- Aligns container lifecycle with servers that lack durable semantic DBs (RA, pyright).
- Gives gopls/TS a path to cheaper reconnects via disk artifacts.
- Makes `index_status=ready` less misleading for large workspaces.

### Negative / risks

- Volume management complexity (permissions, size, GC of `$GOPLSCACHE`).
- Stricter warm criteria may lengthen `warm_index` task latency.
- Shared `target/` / `node_modules` across worktrees can cause cross-talk if mis-bound.

## Alternatives considered

| Option | Why not |
|--------|---------|
| Persist full semantic indexes ourselves | Duplicates LSP internals; fragile across versions |
| Cold-start LSP per scout call | Unacceptable latency for RA/TS large repos |
| Trust progress-end only | gopls/pyright may not emit usable progress; need seed probe |
| Trust seed probe only | Can return symbols before graph/prime finishes → flaky refs |
