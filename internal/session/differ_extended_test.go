package session

import (
	"testing"

	"github.com/blackwell-systems/agent-lsp/internal/types"
)

// TestDiagnosticsEqual_DifferentSeverity tests severity comparison.
func TestDiagnosticsEqual_DifferentSeverity(t *testing.T) {
	a := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 1, // error
		Message:  "undefined variable",
		Source:   "gopls",
	}
	b := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 2, // warning
		Message:  "undefined variable",
		Source:   "gopls",
	}

	if DiagnosticsEqual(a, b) {
		t.Error("expected diagnostics with different severities to be unequal")
	}
}

// TestDiagnosticsEqual_BothSourcesEmpty tests that empty sources match.
func TestDiagnosticsEqual_BothSourcesEmpty(t *testing.T) {
	a := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 1,
		Message:  "undefined variable",
		Source:   "",
	}
	b := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 1,
		Message:  "undefined variable",
		Source:   "",
	}

	if !DiagnosticsEqual(a, b) {
		t.Error("expected diagnostics with both sources empty to be equal")
	}
}

// TestDiagnosticsEqual_DifferentStartLine tests range start line comparison.
func TestDiagnosticsEqual_DifferentStartLine(t *testing.T) {
	a := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 1,
		Message:  "error",
	}
	b := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 11, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 1,
		Message:  "error",
	}

	if DiagnosticsEqual(a, b) {
		t.Error("expected diagnostics with different start lines to be unequal")
	}
}

// TestDiagnosticsEqual_DifferentStartCharacter tests range start character comparison.
func TestDiagnosticsEqual_DifferentStartCharacter(t *testing.T) {
	a := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 1,
		Message:  "error",
	}
	b := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 6},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 1,
		Message:  "error",
	}

	if DiagnosticsEqual(a, b) {
		t.Error("expected diagnostics with different start characters to be unequal")
	}
}

// TestDiagnosticsEqual_DifferentEndLine tests range end line comparison.
func TestDiagnosticsEqual_DifferentEndLine(t *testing.T) {
	a := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 1,
		Message:  "error",
	}
	b := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 11, Character: 15},
		},
		Severity: 1,
		Message:  "error",
	}

	if DiagnosticsEqual(a, b) {
		t.Error("expected diagnostics with different end lines to be unequal")
	}
}

// TestDiagnosticsEqual_DifferentEndCharacter tests range end character comparison.
func TestDiagnosticsEqual_DifferentEndCharacter(t *testing.T) {
	a := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 1,
		Message:  "error",
	}
	b := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 16},
		},
		Severity: 1,
		Message:  "error",
	}

	if DiagnosticsEqual(a, b) {
		t.Error("expected diagnostics with different end characters to be unequal")
	}
}

// TestDiffDiagnostics_DuplicateDiagnostics tests count-based matching with duplicates.
func TestDiffDiagnostics_DuplicateDiagnostics(t *testing.T) {
	// Baseline has 2 copies of the same error
	baseline := []types.LSPDiagnostic{
		{
			Range: types.Range{
				Start: types.Position{Line: 5, Character: 10},
				End:   types.Position{Line: 5, Character: 20},
			},
			Severity: 1,
			Message:  "duplicate error",
			Source:   "gopls",
		},
		{
			Range: types.Range{
				Start: types.Position{Line: 5, Character: 10},
				End:   types.Position{Line: 5, Character: 20},
			},
			Severity: 1,
			Message:  "duplicate error",
			Source:   "gopls",
		},
	}

	// Current has 3 copies (1 introduced)
	current := []types.LSPDiagnostic{
		{
			Range: types.Range{
				Start: types.Position{Line: 5, Character: 10},
				End:   types.Position{Line: 5, Character: 20},
			},
			Severity: 1,
			Message:  "duplicate error",
			Source:   "gopls",
		},
		{
			Range: types.Range{
				Start: types.Position{Line: 5, Character: 10},
				End:   types.Position{Line: 5, Character: 20},
			},
			Severity: 1,
			Message:  "duplicate error",
			Source:   "gopls",
		},
		{
			Range: types.Range{
				Start: types.Position{Line: 5, Character: 10},
				End:   types.Position{Line: 5, Character: 20},
			},
			Severity: 1,
			Message:  "duplicate error",
			Source:   "gopls",
		},
	}

	introduced, resolved := DiffDiagnostics(baseline, current)

	// Should show 1 introduced (3 current - 2 baseline)
	if len(introduced) != 1 {
		t.Errorf("expected 1 introduced with duplicates, got %d", len(introduced))
	}
	if len(resolved) != 0 {
		t.Errorf("expected 0 resolved with duplicates, got %d", len(resolved))
	}
}

// TestDiffDiagnostics_DuplicateResolved tests resolved count with duplicates.
func TestDiffDiagnostics_DuplicateResolved(t *testing.T) {
	// Baseline has 3 copies
	baseline := []types.LSPDiagnostic{
		{
			Range: types.Range{
				Start: types.Position{Line: 5, Character: 10},
				End:   types.Position{Line: 5, Character: 20},
			},
			Severity: 1,
			Message:  "duplicate error",
		},
		{
			Range: types.Range{
				Start: types.Position{Line: 5, Character: 10},
				End:   types.Position{Line: 5, Character: 20},
			},
			Severity: 1,
			Message:  "duplicate error",
		},
		{
			Range: types.Range{
				Start: types.Position{Line: 5, Character: 10},
				End:   types.Position{Line: 5, Character: 20},
			},
			Severity: 1,
			Message:  "duplicate error",
		},
	}

	// Current has 1 copy (2 resolved)
	current := []types.LSPDiagnostic{
		{
			Range: types.Range{
				Start: types.Position{Line: 5, Character: 10},
				End:   types.Position{Line: 5, Character: 20},
			},
			Severity: 1,
			Message:  "duplicate error",
		},
	}

	introduced, resolved := DiffDiagnostics(baseline, current)

	if len(introduced) != 0 {
		t.Errorf("expected 0 introduced, got %d", len(introduced))
	}
	// Should show 2 resolved (3 baseline - 1 current)
	if len(resolved) != 2 {
		t.Errorf("expected 2 resolved with duplicates, got %d", len(resolved))
	}
}

// TestFilterSignificant_OnlyErrorsAndWarnings tests that info and hint are filtered.
func TestFilterSignificant_OnlyErrorsAndWarnings(t *testing.T) {
	diags := []types.LSPDiagnostic{
		{Severity: 1, Message: "error"},
		{Severity: 2, Message: "warning"},
		{Severity: 3, Message: "info"},
		{Severity: 4, Message: "hint"},
	}

	filtered := filterSignificant(diags)

	if len(filtered) != 2 {
		t.Errorf("expected 2 significant diagnostics (error + warning), got %d", len(filtered))
	}

	for _, d := range filtered {
		if d.Severity > 2 {
			t.Errorf("filterSignificant should not include severity %d (%s)", d.Severity, d.Message)
		}
	}
}

// TestFilterSignificant_Empty tests empty input.
func TestFilterSignificant_Empty(t *testing.T) {
	diags := []types.LSPDiagnostic{}
	filtered := filterSignificant(diags)

	if len(filtered) != 0 {
		t.Errorf("expected empty output for empty input, got %d", len(filtered))
	}
}

// TestFilterSignificant_AllInsignificant tests all info/hint diagnostics.
func TestFilterSignificant_AllInsignificant(t *testing.T) {
	diags := []types.LSPDiagnostic{
		{Severity: 3, Message: "info 1"},
		{Severity: 4, Message: "hint 1"},
		{Severity: 3, Message: "info 2"},
		{Severity: 4, Message: "hint 2"},
	}

	filtered := filterSignificant(diags)

	if len(filtered) != 0 {
		t.Errorf("expected 0 significant diagnostics (all info/hint), got %d", len(filtered))
	}
}

// TestDiagnosticFingerprint_Uniqueness tests that fingerprints are unique.
func TestDiagnosticFingerprint_Uniqueness(t *testing.T) {
	d1 := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 1,
		Message:  "error 1",
	}
	d2 := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 2,
		Message:  "error 1",
	}
	d3 := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 1,
		Message:  "error 2",
	}

	fp1 := diagnosticFingerprint(d1)
	fp2 := diagnosticFingerprint(d2)
	fp3 := diagnosticFingerprint(d3)

	if fp1 == fp2 {
		t.Error("fingerprints should differ for different severities")
	}
	if fp1 == fp3 {
		t.Error("fingerprints should differ for different messages")
	}
	if fp2 == fp3 {
		t.Error("fingerprints should differ when both severity and message differ")
	}
}

// TestDiagnosticFingerprint_IgnoresSource tests that Source is not in fingerprint.
func TestDiagnosticFingerprint_IgnoresSource(t *testing.T) {
	d1 := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 1,
		Message:  "error",
		Source:   "gopls",
	}
	d2 := types.LSPDiagnostic{
		Range: types.Range{
			Start: types.Position{Line: 10, Character: 5},
			End:   types.Position{Line: 10, Character: 15},
		},
		Severity: 1,
		Message:  "error",
		Source:   "eslint",
	}

	fp1 := diagnosticFingerprint(d1)
	fp2 := diagnosticFingerprint(d2)

	if fp1 != fp2 {
		t.Error("fingerprints should be identical when only Source differs")
	}
}

// TestDiffDiagnostics_EmptyBoth tests both baseline and current empty.
func TestDiffDiagnostics_EmptyBoth(t *testing.T) {
	baseline := []types.LSPDiagnostic{}
	current := []types.LSPDiagnostic{}

	introduced, resolved := DiffDiagnostics(baseline, current)

	if len(introduced) != 0 {
		t.Errorf("expected 0 introduced when both empty, got %d", len(introduced))
	}
	if len(resolved) != 0 {
		t.Errorf("expected 0 resolved when both empty, got %d", len(resolved))
	}
}

// TestDiffDiagnostics_OneIndexedPositions tests that output positions are 1-indexed.
func TestDiffDiagnostics_OneIndexedPositions(t *testing.T) {
	// LSP uses 0-indexed positions
	current := []types.LSPDiagnostic{
		{
			Range: types.Range{
				Start: types.Position{Line: 0, Character: 0}, // 0-indexed
				End:   types.Position{Line: 0, Character: 10},
			},
			Severity: 1,
			Message:  "error at start",
		},
	}

	introduced, _ := DiffDiagnostics([]types.LSPDiagnostic{}, current)

	if len(introduced) != 1 {
		t.Fatalf("expected 1 introduced, got %d", len(introduced))
	}

	// Output should be 1-indexed
	if introduced[0].Line != 1 || introduced[0].Col != 1 {
		t.Errorf("expected 1-indexed position (1,1), got (%d,%d)", introduced[0].Line, introduced[0].Col)
	}
}
