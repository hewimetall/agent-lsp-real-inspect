---
polywave_name: '[polywave:wave1:agent-A] ## Type Mapping Layer and EncodeResult Integration'
---

# Agent A Brief - Wave 1

**IMPL Doc:** /Users/dayna.blackwell/code/agent-lsp/docs/IMPL/IMPL-gcf-graph-encoding.yaml

## Files Owned

- `internal/encoding/gcf/graph.go`
- `internal/encoding/gcf/graph_test.go`
- `internal/tools/helpers.go`
- `internal/tools/helpers_test.go`


## Task

## Type Mapping Layer and EncodeResult Integration

### What to implement

**File 1: internal/encoding/gcf/graph.go (NEW)**

Create the graph encoding bridge between agent-lsp's LSP types and gcf-go's
Payload/Symbol/Edge types. This file provides all shared helpers that Wave 2
tool handlers will use.

Functions to implement:

1. `MapSymbolKind(kind types.SymbolKind) string`
   Map LSP SymbolKind integers to gcf-go kind strings. Mapping:
   - 1 (File) -> "file"
   - 2 (Module) -> "package"
   - 3 (Namespace) -> "package"
   - 4 (Package) -> "package"
   - 5 (Class) -> "class"
   - 6 (Method) -> "method"
   - 7 (Property) -> "field"
   - 8 (Field) -> "field"
   - 9 (Constructor) -> "method"
   - 10 (Enum) -> "type"
   - 11 (Interface) -> "interface"
   - 12 (Function) -> "function"
   - 13 (Variable) -> "var"
   - 14 (Constant) -> "const"
   - 15 (String) -> "const"
   - 16 (Number) -> "const"
   - 17 (Boolean) -> "const"
   - 18 (Array) -> "type"
   - 19 (Object) -> "type"
   - 20 (Key) -> "field"
   - 21 (Null) -> "const"
   - 22 (EnumMember) -> "const"
   - 23 (Struct) -> "type"
   - 24 (Event) -> "function"
   - 25 (Operator) -> "function"
   - 26 (TypeParameter) -> "type"
   - default -> "var"

2. `QualifiedName(filePath, symbolName string) string`
   Derive qualified name from file path and symbol name.
   - Extract the directory-based package path from filePath
   - Use the two last path segments for brevity (e.g., "tools/change_impact")
   - Format: "pkg/path.SymbolName"
   - Handle empty filePath gracefully (return just symbolName)

3. `BuildGraphPayload(tool string, symbols []gcfgo.Symbol, edges []gcfgo.Edge) *gcfgo.Payload`
   Convenience constructor. Returns:
   ```go
   &gcfgo.Payload{
       Tool:    tool,
       Symbols: symbols,
       Edges:   edges,
   }
   ```

4. `EncodeGraph(p *gcfgo.Payload) (string, error)`
   Thin wrapper around `gcfgo.Encode(p)`. Returns error if p is nil.
   ```go
   if p == nil {
       return "", nil
   }
   return gcfgo.Encode(p), nil
   ```

Import: `gcfgo "github.com/blackwell-systems/gcf-go"` and
`"github.com/blackwell-systems/agent-lsp/internal/types"`.

**File 2: internal/encoding/gcf/graph_test.go (NEW)**

Test all four functions:
- TestMapSymbolKind: verify Function(12)->\"function\", Method(6)->\"method\",
  Class(5)->\"class\", Interface(11)->\"interface\", unknown(99)->\"var\"
- TestQualifiedName: verify path extraction, empty path handling
- TestBuildGraphPayload: verify all fields populated, nil symbols/edges -> empty slices
- TestEncodeGraph: verify non-empty output for valid payload, nil returns empty string

**File 3: internal/tools/helpers.go (MODIFY)**

Update EncodeResult to detect *gcfgo.Payload and use graph encoding.

Add import: `gcfgo "github.com/blackwell-systems/gcf-go"`

In the EncodeResult function, modify the "gcf" case. Find this exact text:

```go
case "gcf":
	encoded, err := gcf.Encode(data)
	if err != nil {
		// Fall back to JSON on GCF encoding failure
		raw, _ := json.Marshal(data)
		return types.TextResult(string(raw)), nil
	}
	return types.TextResult(encoded), nil
```

Replace with:

```go
case "gcf":
	// Graph-profile: if data is already a *gcf.Payload, use graph encoding
	if p, ok := data.(*gcfgo.Payload); ok {
		encoded, err := gcf.EncodeGraph(p)
		if err != nil {
			raw, _ := json.Marshal(data)
			return types.TextResult(string(raw)), nil
		}
		return types.TextResult(encoded), nil
	}
	// Tabular fallback for non-Payload data
	encoded, err := gcf.Encode(data)
	if err != nil {
		raw, _ := json.Marshal(data)
		return types.TextResult(string(raw)), nil
	}
	return types.TextResult(encoded), nil
```

**File 4: internal/tools/helpers_test.go (MODIFY)**

Add test for the new Payload path in EncodeResult:

```go
func TestEncodeResult_GCF_GraphPayload(t *testing.T) {
    ctx := ContextWithOutputFormat(context.Background(), "gcf")
    p := &gcfgo.Payload{
        Tool: "test_tool",
        Symbols: []gcfgo.Symbol{
            {QualifiedName: "pkg.Func", Kind: "function", Score: 1.0, Provenance: "lsp_resolved", Distance: 0},
        },
        Edges: []gcfgo.Edge{
            {Source: "pkg.Func", Target: "pkg.Caller", EdgeType: "called_by"},
        },
    }
    result, err := EncodeResult(ctx, p)
    // verify no error, non-empty text, contains "pkg.Func"
}
```

Add import: `gcfgo "github.com/blackwell-systems/gcf-go"` to the test file.

### Interfaces

- `EncodeGraph(p *gcfgo.Payload) (string, error)` in internal/encoding/gcf/graph.go
- `MapSymbolKind(kind types.SymbolKind) string` in internal/encoding/gcf/graph.go
- `QualifiedName(filePath, symbolName string) string` in internal/encoding/gcf/graph.go
- `BuildGraphPayload(tool string, symbols []gcfgo.Symbol, edges []gcfgo.Edge) *gcfgo.Payload` in internal/encoding/gcf/graph.go

### Tests

- internal/encoding/gcf/graph_test.go: 4+ test functions covering all helpers
- internal/tools/helpers_test.go: 1 new test for Payload-aware EncodeResult

### Verification gate

```bash
GOWORK=off go build ./internal/encoding/gcf/... && \
GOWORK=off go vet ./internal/encoding/gcf/... && \
GOWORK=off go test ./internal/encoding/gcf/... && \
GOWORK=off go test ./internal/tools/ -run TestEncodeResult
```

Postconditions:
```bash
# (a) EncodeGraph function exists
grep -c "func EncodeGraph" internal/encoding/gcf/graph.go
# expected: 1
# (b) MapSymbolKind function exists
grep -c "func MapSymbolKind" internal/encoding/gcf/graph.go
# expected: 1
# (c) EncodeResult handles *gcfgo.Payload
grep -c "gcfgo.Payload" internal/tools/helpers.go
# expected: >= 1
```

### Constraints

- Do NOT modify internal/encoding/gcf/encode.go. The existing Encode()
  function for tabular encoding must remain unchanged.
- Do NOT modify any tool handler files (change_impact.go, etc.). Those
  are owned by Wave 2 agents.
- Do NOT add any CLI registration or server.go changes.



## Interface Contracts

### EncodeGraphResult

Builds a gcf-go Payload from tool-specific symbol/edge data, then encodes
it using gcf.Encode. Called by EncodeResult when data is *gcf.Payload.


```
// In internal/encoding/gcf/graph.go
func EncodeGraph(p *gcfgo.Payload) (string, error)

```

### EncodeResult format awareness

EncodeResult gains a type switch: if data is *gcf.Payload and format is
"gcf", call gcf.EncodeGraph(). Otherwise fall through to existing paths.


```
// In internal/tools/helpers.go, updated EncodeResult:
func EncodeResult(ctx context.Context, data any) (types.ToolResult, error)
// When format == "gcf":
//   if p, ok := data.(*gcfgo.Payload); ok { return gcf.EncodeGraph(p) }
//   else { return gcf.Encode(data) }  // existing tabular fallback

```

### MapSymbolKind

Maps LSP SymbolKind int to gcf-go kind string using KindAbbrev-compatible
names (function, method, type, interface, class, field, var, const, etc.).


```
// In internal/encoding/gcf/graph.go
func MapSymbolKind(kind types.SymbolKind) string

```

### QualifiedName

Derives a qualified name from a file path and symbol name.
Format: "pkg/path.SymbolName" (Go convention).


```
// In internal/encoding/gcf/graph.go
func QualifiedName(filePath, symbolName string) string

```

### BuildGraphPayload

Convenience constructor that creates a *gcf.Payload with tool name,
symbols, and edges populated. Used by each tool handler to build
the Payload before passing to EncodeResult.


```
// In internal/encoding/gcf/graph.go
func BuildGraphPayload(tool string, symbols []gcfgo.Symbol, edges []gcfgo.Edge) *gcfgo.Payload

```



## Quality Gates

Level: standard

- **build**: `GOWORK=off go build ./...` (required: true)
- **lint**: `GOWORK=off go vet ./...` (required: true)
- **test**: `GOWORK=off go test ./internal/... ./cmd/...` (required: true)

