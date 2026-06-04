# Common Workflows

What you want to do, and which agent-lsp tool or skill gets you there.

## Before editing code

| I want to... | Use | Why |
|---|---|---|
| See what breaks if I change this file | `blast_radius` | Returns all exports + all callers (test vs non-test) in one call |
| Understand what a function does | `inspect_symbol` | Type info, docs, signature without opening the file |
| See the full picture of unfamiliar code | `/lsp-understand` | Builds a Code Map: type info, implementations, call hierarchy, references, source |
| Find all usages of a symbol | `find_references` | Every file that uses this symbol across the workspace |
| Check what calls this function | `find_callers` | Call hierarchy with concurrent boundary detection |

## Making changes

| I want to... | Use | Why |
|---|---|---|
| Rename a symbol safely | `/lsp-rename` | Two-phase: shows all affected sites, then renames atomically via LSP |
| Edit a function by name | `/lsp-edit-symbol` | Resolves to definition, gets full range, applies edit |
| Change an exported API | `/lsp-edit-export` | Finds all callers first so nothing breaks silently |
| Extract a code block into a function | `/lsp-extract-function` | Uses LSP code actions, falls back to manual extraction |
| Preview an edit before applying | `preview_edit` | Shows diagnostic delta without touching disk |
| Apply an edit only if safe | `/lsp-safe-edit` | Previews, checks error delta, applies only if acceptable |

## Refactoring

| I want to... | Use | Why |
|---|---|---|
| End-to-end safe refactor | `/lsp-refactor` | Impact analysis, preview, apply, verify build, run tests |
| Simulate changes before committing | `/lsp-simulate` | Edit files in memory, check diagnostics, apply or discard |
| Find dead code | `/lsp-dead-code` | Lists exports with zero references across workspace |
| Find all implementations of an interface | `/lsp-implement` | Concrete types that satisfy the interface |

## After editing code

| I want to... | Use | Why |
|---|---|---|
| Check for errors | `get_diagnostics` | LSP diagnostics for a file |
| Verify nothing broke | `/lsp-verify` | Three layers: LSP diagnostics + build + test suite |
| Find which tests to run | `/lsp-test-correlation` | Discovers test files that cover your changed file |
| Format code | `/lsp-format-code` | Language server formatter |

## Exploring a codebase

| I want to... | Use | Why |
|---|---|---|
| Get a project overview | `/lsp-architecture` | Languages, packages, entry points, dependency graph |
| Find a symbol by name | `find_symbol` | Workspace-wide symbol search |
| See all symbols in a file | `list_symbols` | Document symbol tree |
| Quick lookup on any symbol | `/lsp-explore` | Hover + implementations + call hierarchy + references in one pass |
| Deep documentation lookup | `/lsp-docs` | Three-tier: hover, offline toolchain docs, source definition |

## Code quality

| I want to... | Use | Why |
|---|---|---|
| Audit a file for issues | `/lsp-inspect` | Dead symbols, silent failures, error wrapping, coverage gaps, doc drift |
| Check concurrency safety | `/lsp-concurrency-audit` | Maps fields, traces goroutine access, finds unguarded shared state |
| Get quick fixes for errors | `/lsp-fix-all` | Applies available code actions for all diagnostics in a file |
| Generate interface stubs | `/lsp-generate` | Implement interface, generate test skeletons, add missing methods |
