package gcf

import (
	"path/filepath"
	"strings"

	gcfgo "github.com/blackwell-systems/gcf-go"
	"github.com/blackwell-systems/agent-lsp/internal/types"
)

// MapSymbolKind maps an LSP SymbolKind integer to a gcf-go kind string.
// Uses KindAbbrev-compatible names: function, method, type, interface,
// class, field, var, const, package, file.
func MapSymbolKind(kind types.SymbolKind) string {
	switch int(kind) {
	case 1: // File
		return "file"
	case 2, 3, 4: // Module, Namespace, Package
		return "package"
	case 5: // Class
		return "class"
	case 6: // Method
		return "method"
	case 7, 8, 20: // Property, Field, Key
		return "field"
	case 9: // Constructor
		return "method"
	case 10: // Enum
		return "type"
	case 11: // Interface
		return "interface"
	case 12: // Function
		return "function"
	case 13: // Variable
		return "var"
	case 14, 15, 16, 17, 21, 22: // Constant, String, Number, Boolean, Null, EnumMember
		return "const"
	case 18, 19, 23, 26: // Array, Object, Struct, TypeParameter
		return "type"
	case 24, 25: // Event, Operator
		return "function"
	default:
		return "var"
	}
}

// QualifiedName derives a qualified name from a file path and symbol name.
// Format: "pkg/path.SymbolName" using the last two path segments for brevity.
// Returns just symbolName when filePath is empty.
func QualifiedName(filePath, symbolName string) string {
	if filePath == "" {
		return symbolName
	}
	dir := filepath.Dir(filePath)
	parts := strings.Split(filepath.ToSlash(dir), "/")
	// Use last two path segments for brevity (e.g., "tools/change_impact")
	if len(parts) > 2 {
		parts = parts[len(parts)-2:]
	}
	pkg := strings.Join(parts, "/")
	return pkg + "." + symbolName
}

// BuildGraphPayload creates a *gcfgo.Payload with the given tool name,
// symbols, and edges. Used by each tool handler to construct the Payload
// before passing to EncodeResult.
func BuildGraphPayload(tool string, symbols []gcfgo.Symbol, edges []gcfgo.Edge) *gcfgo.Payload {
	if symbols == nil {
		symbols = []gcfgo.Symbol{}
	}
	if edges == nil {
		edges = []gcfgo.Edge{}
	}
	return &gcfgo.Payload{
		Tool:    tool,
		Symbols: symbols,
		Edges:   edges,
	}
}

// EncodeGraph encodes a *gcfgo.Payload into GCF graph format string.
// Returns empty string for nil payloads.
func EncodeGraph(p *gcfgo.Payload) (string, error) {
	if p == nil {
		return "", nil
	}
	return gcfgo.Encode(p), nil
}
