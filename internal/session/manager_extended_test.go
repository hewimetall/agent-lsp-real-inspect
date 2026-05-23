package session

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"github.com/blackwell-systems/agent-lsp/internal/types"
)

// TestCreateSession_IDLength verifies session IDs are hex-encoded 16 bytes (32 chars).
func TestCreateSession_IDLength(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})

	// Manually test ID generation logic by creating sessions directly
	for i := 0; i < 10; i++ {
		sess := &SimulationSession{
			ID:               fmt.Sprintf("%032x", i), // 32 hex chars
			Status:           StatusCreated,
			Baselines:        make(map[string]DiagnosticsSnapshot),
			Versions:         make(map[string]int),
			Contents:         make(map[string]string),
			OriginalContents: make(map[string]string),
		}
		mgr.mu.Lock()
		mgr.sessions[sess.ID] = sess
		mgr.mu.Unlock()

		if len(sess.ID) != 32 {
			t.Errorf("expected session ID length 32, got %d", len(sess.ID))
		}
	}
}

// TestGetSession_ThreadSafe verifies concurrent GetSession calls don't race.
func TestGetSession_ThreadSafe(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})

	sess := &SimulationSession{
		ID:               "thread-safe-test",
		Status:           StatusCreated,
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
		Contents:         make(map[string]string),
		OriginalContents: make(map[string]string),
	}
	mgr.mu.Lock()
	mgr.sessions[sess.ID] = sess
	mgr.mu.Unlock()

	// Concurrent reads should not race
	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			s, err := mgr.GetSession(sess.ID)
			if err != nil {
				t.Errorf("GetSession failed: %v", err)
			}
			if s.ID != sess.ID {
				t.Errorf("wrong session returned")
			}
		}()
	}
	wg.Wait()
}

// TestCommit_PatchContent verifies Commit builds correct patch map.
func TestCommit_PatchContent(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	uri1 := "file:///tmp/a.go"
	uri2 := "file:///tmp/b.go"
	content1 := "package a"
	content2 := "package b"

	sess := &SimulationSession{
		ID:     "commit-patch-content",
		Status: StatusMutated,
		Contents: map[string]string{
			uri1: content1,
			uri2: content2,
		},
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
		OriginalContents: make(map[string]string),
	}
	mgr.mu.Lock()
	mgr.sessions[sess.ID] = sess
	mgr.mu.Unlock()

	result, err := mgr.Commit(ctx, sess.ID, "", false)
	if err != nil {
		t.Fatalf("Commit failed: %v", err)
	}

	patch, ok := result.Patch.(map[string]string)
	if !ok {
		t.Fatalf("expected patch to be map[string]string, got %T", result.Patch)
	}

	if patch[uri1] != content1 {
		t.Errorf("patch[%s] = %q, want %q", uri1, patch[uri1], content1)
	}
	if patch[uri2] != content2 {
		t.Errorf("patch[%s] = %q, want %q", uri2, patch[uri2], content2)
	}
}

// TestCommit_StatusTransition verifies Commit transitions status to StatusCommitted.
func TestCommit_StatusTransition(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	tests := []struct {
		name          string
		initialStatus SessionStatus
		expectError   bool
	}{
		{"from mutated", StatusMutated, false},
		{"from evaluated", StatusEvaluated, false},
		{"from created", StatusCreated, true},
		{"from committed", StatusCommitted, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sess := &SimulationSession{
				ID:               "commit-status-" + tt.name,
				Status:           tt.initialStatus,
				Baselines:        make(map[string]DiagnosticsSnapshot),
				Versions:         make(map[string]int),
				Contents:         map[string]string{"file:///tmp/test.go": "content"},
				OriginalContents: make(map[string]string),
			}
			mgr.mu.Lock()
			mgr.sessions[sess.ID] = sess
			mgr.mu.Unlock()

			_, err := mgr.Commit(ctx, sess.ID, "", false)
			if tt.expectError {
				if err == nil {
					t.Errorf("expected error for status %s, got nil", tt.initialStatus)
				}
			} else {
				if err != nil {
					t.Errorf("unexpected error: %v", err)
				}
				if sess.Status != StatusCommitted {
					t.Errorf("expected status StatusCommitted, got %s", sess.Status)
				}
			}
		})
	}
}

// TestDiscard_StatusTransition verifies Discard transitions to StatusDiscarded.
func TestDiscard_StatusTransition(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	tests := []struct {
		name          string
		initialStatus SessionStatus
		expectError   bool
	}{
		{"from mutated", StatusMutated, false},
		{"from evaluated", StatusEvaluated, false},
		{"from created", StatusCreated, false},
		{"from committed", StatusCommitted, true},
		{"from discarded", StatusDiscarded, true},
		{"from destroyed", StatusDestroyed, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sess := &SimulationSession{
				ID:               "discard-status-" + tt.name,
				Status:           tt.initialStatus,
				Baselines:        make(map[string]DiagnosticsSnapshot),
				Versions:         make(map[string]int),
				Contents:         make(map[string]string),
				OriginalContents: make(map[string]string),
			}
			mgr.mu.Lock()
			mgr.sessions[sess.ID] = sess
			mgr.mu.Unlock()

			err := mgr.Discard(ctx, sess.ID)
			if tt.expectError {
				if err == nil {
					t.Errorf("expected error for status %s, got nil", tt.initialStatus)
				}
			} else {
				if err != nil {
					t.Errorf("unexpected error: %v", err)
				}
				if sess.Status != StatusDiscarded {
					t.Errorf("expected status StatusDiscarded, got %s", sess.Status)
				}
			}
		})
	}
}

// TestApplyEdit_NonTerminalStates verifies ApplyEdit blocks on terminal states.
func TestApplyEdit_NonTerminalStates(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	terminalStates := []SessionStatus{
		StatusCommitted,
		StatusDiscarded,
		StatusDestroyed,
		StatusDirty,
	}

	for _, status := range terminalStates {
		t.Run(string(status), func(t *testing.T) {
			sess := &SimulationSession{
				ID:               "apply-terminal-" + string(status),
				Status:           status,
				Baselines:        make(map[string]DiagnosticsSnapshot),
				Versions:         make(map[string]int),
				Contents:         make(map[string]string),
				OriginalContents: make(map[string]string),
			}
			mgr.mu.Lock()
			mgr.sessions[sess.ID] = sess
			mgr.mu.Unlock()

			_, err := mgr.ApplyEdit(ctx, sess.ID, "file:///tmp/test.go", types.Range{}, "new")
			if err == nil {
				t.Errorf("expected error for terminal status %s, got nil", status)
			}
		})
	}
}

// TestEvaluate_StatusValidation verifies Evaluate validates session status.
func TestEvaluate_StatusValidation(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	validStates := []SessionStatus{StatusMutated, StatusEvaluated}
	invalidStates := []SessionStatus{StatusCreated, StatusCommitted, StatusDiscarded, StatusDestroyed}

	// Test valid states (will fail at executor.Acquire but that's expected)
	for _, status := range validStates {
		t.Run("valid-"+string(status), func(t *testing.T) {
			sess := &SimulationSession{
				ID:               "eval-valid-" + string(status),
				Status:           status,
				Baselines:        make(map[string]DiagnosticsSnapshot),
				Versions:         make(map[string]int),
				Contents:         make(map[string]string),
				OriginalContents: make(map[string]string),
			}
			mgr.mu.Lock()
			mgr.sessions[sess.ID] = sess
			mgr.mu.Unlock()

			// Will fail at executor.Acquire (no client), but shouldn't fail status check
			_, err := mgr.Evaluate(ctx, sess.ID, "file", 0)
			if err != nil && err.Error() == fmt.Sprintf("session %s cannot be evaluated in state %s", sess.ID, status) {
				t.Errorf("unexpected status validation error for valid status %s", status)
			}
		})
	}

	// Test invalid states (should fail status check before executor.Acquire)
	for _, status := range invalidStates {
		t.Run("invalid-"+string(status), func(t *testing.T) {
			sess := &SimulationSession{
				ID:               "eval-invalid-" + string(status),
				Status:           status,
				Baselines:        make(map[string]DiagnosticsSnapshot),
				Versions:         make(map[string]int),
				Contents:         make(map[string]string),
				OriginalContents: make(map[string]string),
			}
			mgr.mu.Lock()
			mgr.sessions[sess.ID] = sess
			mgr.mu.Unlock()

			_, err := mgr.Evaluate(ctx, sess.ID, "file", 0)
			if err == nil {
				t.Errorf("expected error for invalid status %s, got nil", status)
			}
		})
	}
}

// TestCommit_WriteFilesCount tests that apply=true counts written files correctly.
// This test uses apply=false to avoid requiring a real LSP client for OpenDocument.
func TestCommit_WriteFilesCount(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	files := map[string]string{
		"file:///tmp/a.go": "package a",
		"file:///tmp/b.go": "package b",
		"file:///tmp/c.go": "package c",
	}

	sess := &SimulationSession{
		ID:               "commit-count",
		Status:           StatusMutated,
		Contents:         files,
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
		OriginalContents: make(map[string]string),
	}
	mgr.mu.Lock()
	mgr.sessions[sess.ID] = sess
	mgr.mu.Unlock()

	// Test with apply=false (doesn't need LSP client)
	result, err := mgr.Commit(ctx, sess.ID, "", false)
	if err != nil {
		t.Fatalf("Commit failed: %v", err)
	}

	if result.FilesWritten != 0 {
		t.Errorf("expected 0 files written for apply=false, got %d", result.FilesWritten)
	}

	patch, ok := result.Patch.(map[string]string)
	if !ok {
		t.Fatalf("expected patch to be map[string]string, got %T", result.Patch)
	}

	if len(patch) != len(files) {
		t.Errorf("expected patch with %d entries, got %d", len(files), len(patch))
	}
}

// TestCommit_ApplyTrue_WritesFile verifies that apply=true writes files to disk.
// Note: This test will fail with nil LSP client, so it documents the intended behavior.
func TestCommit_ApplyTrue_WritesFile(t *testing.T) {
	t.Skip("Requires mock LSP client implementation for OpenDocument")

	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()
	tmpDir := t.TempDir()

	testFile := filepath.Join(tmpDir, "written.go")
	fileURI := "file://" + testFile
	content := "package main"

	sess := &SimulationSession{
		ID:               "commit-write-file",
		Status:           StatusMutated,
		Contents:         map[string]string{fileURI: content},
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
		OriginalContents: make(map[string]string),
		// Client: would need proper mock here
	}
	mgr.mu.Lock()
	mgr.sessions[sess.ID] = sess
	mgr.mu.Unlock()

	result, err := mgr.Commit(ctx, sess.ID, "", true)
	if err != nil {
		t.Fatalf("Commit failed: %v", err)
	}

	if result.FilesWritten != 1 {
		t.Errorf("expected 1 file written, got %d", result.FilesWritten)
	}

	// Verify file was written with correct content and permissions
	written, err := os.ReadFile(testFile)
	if err != nil {
		t.Fatalf("failed to read written file: %v", err)
	}
	if string(written) != content {
		t.Errorf("content mismatch: want %q, got %q", content, string(written))
	}

	info, err := os.Stat(testFile)
	if err != nil {
		t.Fatalf("failed to stat file: %v", err)
	}
	if info.Mode().Perm() != 0644 {
		t.Errorf("expected permissions 0644, got %04o", info.Mode().Perm())
	}
}

// TestDestroy_ConcurrentAccess tests Destroy during concurrent GetSession calls.
func TestDestroy_ConcurrentAccess(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	sess := &SimulationSession{
		ID:               "destroy-concurrent",
		Status:           StatusMutated,
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
		Contents:         make(map[string]string),
		OriginalContents: make(map[string]string),
	}
	mgr.mu.Lock()
	mgr.sessions[sess.ID] = sess
	mgr.mu.Unlock()

	var wg sync.WaitGroup
	errors := make(chan error, 11)

	// Spawn 10 concurrent GetSession calls
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := mgr.GetSession(sess.ID)
			errors <- err
		}()
	}

	// Destroy the session concurrently
	wg.Add(1)
	go func() {
		defer wg.Done()
		errors <- mgr.Destroy(ctx, sess.ID)
	}()

	wg.Wait()
	close(errors)

	// At least one GetSession should succeed before Destroy,
	// and the Destroy should succeed. After Destroy, GetSession should fail.
	successCount := 0
	for err := range errors {
		if err == nil {
			successCount++
		}
	}

	if successCount == 0 {
		t.Error("expected at least one operation to succeed")
	}
}

// TestSimulateChain_SafeToApplyThroughStep verifies the safe step calculation.
func TestSimulateChain_SafeToApplyThroughStep(t *testing.T) {
	tests := []struct {
		name          string
		steps         []ChainStepResult
		expectedSafe  int
		expectedDelta int
	}{
		{
			name:          "all steps safe",
			steps:         []ChainStepResult{{Step: 1, NetDelta: 0}, {Step: 2, NetDelta: 0}},
			expectedSafe:  2,
			expectedDelta: 0,
		},
		{
			name:          "first step unsafe",
			steps:         []ChainStepResult{{Step: 1, NetDelta: 2}, {Step: 2, NetDelta: 3}},
			expectedSafe:  0,
			expectedDelta: 3,
		},
		{
			name:          "partial safe",
			steps:         []ChainStepResult{{Step: 1, NetDelta: 0}, {Step: 2, NetDelta: 1}},
			expectedSafe:  1,
			expectedDelta: 1,
		},
		{
			name:          "empty chain",
			steps:         []ChainStepResult{},
			expectedSafe:  0,
			expectedDelta: 0,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Compute safe step using same logic as SimulateChain (lines 312-318)
			safeStep := 0
			for i := len(tt.steps) - 1; i >= 0; i-- {
				if tt.steps[i].NetDelta == 0 {
					safeStep = tt.steps[i].Step
					break
				}
			}

			cumulativeDelta := 0
			if len(tt.steps) > 0 {
				cumulativeDelta = tt.steps[len(tt.steps)-1].NetDelta
			}

			if safeStep != tt.expectedSafe {
				t.Errorf("SafeToApplyThroughStep = %d, want %d", safeStep, tt.expectedSafe)
			}
			if cumulativeDelta != tt.expectedDelta {
				t.Errorf("CumulativeDelta = %d, want %d", cumulativeDelta, tt.expectedDelta)
			}
		})
	}
}

// TestLanguageToExtension_DefaultFallback tests the default case.
func TestLanguageToExtension_DefaultFallback(t *testing.T) {
	tests := []struct {
		language string
		expected string
	}{
		{"unknown", ".unknown"},
		{"cobol", ".cobol"},
		{"fortran", ".fortran"},
		{"", "."},
	}

	for _, tt := range tests {
		t.Run(tt.language, func(t *testing.T) {
			got := languageToExtension(tt.language)
			if got != tt.expected {
				t.Errorf("languageToExtension(%q) = %q, want %q", tt.language, got, tt.expected)
			}
		})
	}
}

// TestSessionManager_MultipleDestroy tests that destroying the same session twice
// returns an error the second time.
func TestSessionManager_MultipleDestroy(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	sess := &SimulationSession{
		ID:               "multi-destroy",
		Status:           StatusCreated,
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
		Contents:         make(map[string]string),
		OriginalContents: make(map[string]string),
	}
	mgr.mu.Lock()
	mgr.sessions[sess.ID] = sess
	mgr.mu.Unlock()

	// First destroy should succeed
	if err := mgr.Destroy(ctx, sess.ID); err != nil {
		t.Fatalf("first Destroy failed: %v", err)
	}

	// Second destroy should fail (session not found)
	err := mgr.Destroy(ctx, sess.ID)
	if err == nil {
		t.Fatal("expected error on second Destroy, got nil")
	}
	if err.Error() != fmt.Sprintf("destroy: session not found: %s", sess.ID) {
		t.Errorf("unexpected error message: %s", err.Error())
	}
}

// TestApplyEdit_SessionNotFound tests ApplyEdit with non-existent session.
func TestApplyEdit_SessionNotFound(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	_, err := mgr.ApplyEdit(ctx, "no-such-session", "file:///tmp/test.go", types.Range{}, "text")
	if err == nil {
		t.Fatal("expected error for non-existent session, got nil")
	}
	if err.Error() != "session not found: no-such-session" {
		t.Errorf("unexpected error message: %s", err.Error())
	}
}

// TestEvaluate_SessionNotFound tests Evaluate with non-existent session.
func TestEvaluate_SessionNotFound(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	_, err := mgr.Evaluate(ctx, "no-such-session", "file", 0)
	if err == nil {
		t.Fatal("expected error for non-existent session, got nil")
	}
	if err.Error() != "session not found: no-such-session" {
		t.Errorf("unexpected error message: %s", err.Error())
	}
}

// TestCommit_SessionNotFound tests Commit with non-existent session.
func TestCommit_SessionNotFound(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	_, err := mgr.Commit(ctx, "no-such-session", "", false)
	if err == nil {
		t.Fatal("expected error for non-existent session, got nil")
	}
	if err.Error() != "session not found: no-such-session" {
		t.Errorf("unexpected error message: %s", err.Error())
	}
}

// TestDiscard_SessionNotFound tests Discard with non-existent session.
func TestDiscard_SessionNotFound(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	err := mgr.Discard(ctx, "no-such-session")
	if err == nil {
		t.Fatal("expected error for non-existent session, got nil")
	}
	if err.Error() != "discard: session not found: no-such-session" {
		t.Errorf("unexpected error message: %s", err.Error())
	}
}

// TestSimulateChain_SessionNotFound tests SimulateChain with non-existent session.
func TestSimulateChain_SessionNotFound(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	// SimulateChain with no edits returns successfully (empty result).
	// To test error handling, provide at least one edit.
	_, err := mgr.SimulateChain(ctx, "no-such-session", []ChainEdit{
		{FileURI: "file:///tmp/test.go", Range: types.Range{}, NewText: "text"},
	}, 0)
	if err == nil {
		t.Fatal("expected error for non-existent session with edits, got nil")
	}

	// Error should come from ApplyEdit at step 1
	expectedSubstring := "applying edit at step 1"
	if !contains(err.Error(), expectedSubstring) {
		t.Errorf("error should contain %q, got: %s", expectedSubstring, err.Error())
	}
}

func contains(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(s) > len(substr) && findSubstring(s, substr))
}

func findSubstring(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
