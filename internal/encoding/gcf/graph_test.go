package gcf

import (
	"testing"

	gcfgo "github.com/blackwell-systems/gcf-go"
	"github.com/blackwell-systems/agent-lsp/internal/types"
)

func TestMapSymbolKind(t *testing.T) {
	tests := []struct {
		kind types.SymbolKind
		want string
	}{
		{12, "function"},
		{6, "method"},
		{5, "class"},
		{11, "interface"},
		{13, "var"},
		{14, "const"},
		{1, "file"},
		{2, "package"},
		{3, "package"},
		{4, "package"},
		{7, "field"},
		{8, "field"},
		{9, "method"},
		{10, "type"},
		{15, "const"},
		{16, "const"},
		{17, "const"},
		{18, "type"},
		{19, "type"},
		{20, "field"},
		{21, "const"},
		{22, "const"},
		{23, "type"},
		{24, "function"},
		{25, "function"},
		{26, "type"},
		{99, "var"},
	}
	for _, tt := range tests {
		got := MapSymbolKind(tt.kind)
		if got != tt.want {
			t.Errorf("MapSymbolKind(%d) = %q, want %q", tt.kind, got, tt.want)
		}
	}
}

func TestQualifiedName(t *testing.T) {
	tests := []struct {
		filePath   string
		symbolName string
		want       string
	}{
		{"/src/pkg/tools/change_impact.go", "Foo", "pkg/tools.Foo"},
		{"/src/foo.go", "Bar", "/src.Bar"},
		{"", "Baz", "Baz"},
		{"/a.go", "X", "/.X"},
		{"/src/app.ts", "(property) callback", "/src.(property)_callback"},
		{"", "express Router callback", "express_Router_callback"},
		{"/src/lib.ts", "fn<T>(arg: string) => void", "/src.fn<T>(arg:_string)_=>_void"},
	}
	for _, tt := range tests {
		got := QualifiedName(tt.filePath, tt.symbolName)
		if got != tt.want {
			t.Errorf("QualifiedName(%q, %q) = %q, want %q", tt.filePath, tt.symbolName, got, tt.want)
		}
	}
}

func TestBuildGraphPayload(t *testing.T) {
	symbols := []gcfgo.Symbol{
		{QualifiedName: "pkg.Func", Kind: "function", Score: 1.0, Provenance: "lsp_resolved", Distance: 0},
	}
	edges := []gcfgo.Edge{
		{Source: "pkg.Func", Target: "pkg.Caller", EdgeType: "called_by"},
	}

	p := BuildGraphPayload("test_tool", symbols, edges)
	if p.Tool != "test_tool" {
		t.Errorf("Tool = %q, want %q", p.Tool, "test_tool")
	}
	if len(p.Symbols) != 1 {
		t.Errorf("len(Symbols) = %d, want 1", len(p.Symbols))
	}
	if len(p.Edges) != 1 {
		t.Errorf("len(Edges) = %d, want 1", len(p.Edges))
	}

	// Nil symbols/edges should become empty slices
	p2 := BuildGraphPayload("empty", nil, nil)
	if p2.Symbols == nil {
		t.Error("nil symbols should become empty slice")
	}
	if p2.Edges == nil {
		t.Error("nil edges should become empty slice")
	}
	if len(p2.Symbols) != 0 {
		t.Errorf("len(Symbols) = %d, want 0", len(p2.Symbols))
	}
	if len(p2.Edges) != 0 {
		t.Errorf("len(Edges) = %d, want 0", len(p2.Edges))
	}
}

func TestEncodeGraph(t *testing.T) {
	// Valid payload should produce non-empty output
	p := &gcfgo.Payload{
		Tool: "test",
		Symbols: []gcfgo.Symbol{
			{QualifiedName: "pkg.Func", Kind: "function", Score: 1.0, Provenance: "lsp_resolved", Distance: 0},
		},
		Edges: []gcfgo.Edge{},
	}
	encoded, err := EncodeGraph(p)
	if err != nil {
		t.Fatalf("EncodeGraph returned error: %v", err)
	}
	if encoded == "" {
		t.Error("EncodeGraph returned empty string for valid payload")
	}
	if len(encoded) < 10 {
		t.Errorf("EncodeGraph output suspiciously short: %q", encoded)
	}

	// Nil payload should return empty string
	nilEncoded, nilErr := EncodeGraph(nil)
	if nilErr != nil {
		t.Fatalf("EncodeGraph(nil) returned error: %v", nilErr)
	}
	if nilEncoded != "" {
		t.Errorf("EncodeGraph(nil) = %q, want empty string", nilEncoded)
	}
}
