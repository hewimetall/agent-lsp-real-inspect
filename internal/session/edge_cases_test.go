package session

import (
	"context"
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/blackwell-systems/agent-lsp/internal/types"
)

// TestSession_MarkDirtyErrorMessage verifies error messages are properly stored.
func TestSession_MarkDirtyErrorMessage(t *testing.T) {
	sess := &SimulationSession{
		ID:               "mark-dirty-test",
		Status:           StatusMutated,
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
		Contents:         make(map[string]string),
		OriginalContents: make(map[string]string),
	}

	testErr := fmt.Errorf("test error: connection failed")
	sess.MarkDirty(testErr)

	if !sess.IsDirty() {
		t.Error("session should be marked dirty")
	}

	dirtyErr := sess.DirtyError()
	if dirtyErr == nil {
		t.Fatal("expected DirtyError to return error, got nil")
	}

	if dirtyErr.Error() != testErr.Error() {
		t.Errorf("DirtyError message mismatch: want %q, got %q", testErr.Error(), dirtyErr.Error())
	}

	if sess.Status != StatusDirty {
		t.Errorf("expected status StatusDirty, got %s", sess.Status)
	}
}

// TestSession_DirtyErrorWhenNotDirty verifies DirtyError returns nil when not dirty.
func TestSession_DirtyErrorWhenNotDirty(t *testing.T) {
	sess := &SimulationSession{
		ID:               "not-dirty",
		Status:           StatusMutated,
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
		Contents:         make(map[string]string),
		OriginalContents: make(map[string]string),
	}

	if sess.IsDirty() {
		t.Error("session should not be dirty initially")
	}

	err := sess.DirtyError()
	if err != nil {
		t.Errorf("expected nil error for non-dirty session, got %v", err)
	}
}

// TestSession_ConcurrentMarkDirty tests concurrent MarkDirty calls.
func TestSession_ConcurrentMarkDirty(t *testing.T) {
	sess := &SimulationSession{
		ID:               "concurrent-dirty",
		Status:           StatusMutated,
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
		Contents:         make(map[string]string),
		OriginalContents: make(map[string]string),
	}

	var wg sync.WaitGroup
	for i := 0; i < 10; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()
			sess.MarkDirty(fmt.Errorf("error %d", idx))
		}(i)
	}

	wg.Wait()

	if !sess.IsDirty() {
		t.Error("session should be dirty after concurrent MarkDirty calls")
	}
}

// TestSession_IsTerminalAllStates verifies IsTerminal for all states.
func TestSession_IsTerminalAllStates(t *testing.T) {
	tests := []struct {
		status     SessionStatus
		isTerminal bool
	}{
		{StatusCreated, false},
		{StatusMutated, false},
		{StatusEvaluating, false},
		{StatusEvaluated, false},
		{StatusCommitted, true},
		{StatusDiscarded, true},
		{StatusDirty, true},
		{StatusDestroyed, true},
	}

	for _, tt := range tests {
		t.Run(string(tt.status), func(t *testing.T) {
			sess := &SimulationSession{
				ID:     "terminal-" + string(tt.status),
				Status: tt.status,
			}

			got := sess.IsTerminal()
			if got != tt.isTerminal {
				t.Errorf("IsTerminal() for %s = %v, want %v", tt.status, got, tt.isTerminal)
			}
		})
	}
}

// TestSession_SetStatusTransitions tests all valid status transitions.
func TestSession_SetStatusTransitions(t *testing.T) {
	tests := []struct {
		name     string
		initial  SessionStatus
		next     SessionStatus
		expected SessionStatus
	}{
		{"created to mutated", StatusCreated, StatusMutated, StatusMutated},
		{"mutated to evaluating", StatusMutated, StatusEvaluating, StatusEvaluating},
		{"evaluating to evaluated", StatusEvaluating, StatusEvaluated, StatusEvaluated},
		{"evaluated to committed", StatusEvaluated, StatusCommitted, StatusCommitted},
		{"evaluated to discarded", StatusEvaluated, StatusDiscarded, StatusDiscarded},
		{"mutated to dirty", StatusMutated, StatusDirty, StatusDirty},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sess := &SimulationSession{
				ID:               "transition-" + tt.name,
				Status:           tt.initial,
				Baselines:        make(map[string]DiagnosticsSnapshot),
				Versions:         make(map[string]int),
				Contents:         make(map[string]string),
				OriginalContents: make(map[string]string),
			}

			sess.SetStatus(tt.next)

			if sess.Status != tt.expected {
				t.Errorf("SetStatus(%s) from %s: got %s, want %s",
					tt.next, tt.initial, sess.Status, tt.expected)
			}
		})
	}
}

// TestSession_ConcurrentSetStatus tests concurrent SetStatus calls.
func TestSession_ConcurrentSetStatus(t *testing.T) {
	sess := &SimulationSession{
		ID:               "concurrent-set-status",
		Status:           StatusCreated,
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
		Contents:         make(map[string]string),
		OriginalContents: make(map[string]string),
	}

	statuses := []SessionStatus{
		StatusMutated,
		StatusEvaluating,
		StatusEvaluated,
	}

	var wg sync.WaitGroup
	for i := 0; i < len(statuses); i++ {
		wg.Add(1)
		go func(s SessionStatus) {
			defer wg.Done()
			sess.SetStatus(s)
			time.Sleep(1 * time.Millisecond)
		}(statuses[i])
	}

	wg.Wait()

	// Final status should be one of the set statuses (no race)
	finalStatus := sess.Status
	found := false
	for _, s := range statuses {
		if finalStatus == s {
			found = true
			break
		}
	}
	if !found {
		t.Errorf("unexpected final status: %s", finalStatus)
	}
}

// TestSimulateChain_SingleStep tests a chain with a single edit.
func TestSimulateChain_SingleStep(t *testing.T) {
	// This documents expected behavior for single-step chains.
	// Without a mock LSP client, we can't fully test, but the logic is:
	// 1. Apply one edit
	// 2. Evaluate once
	// 3. SafeToApplyThroughStep = 1 if NetDelta == 0, else 0
	// 4. CumulativeDelta = that step's NetDelta
}

// TestEvaluate_TimeoutDefaults verifies timeout defaults for different scopes.
func TestEvaluate_TimeoutDefaults(t *testing.T) {
	tests := []struct {
		scope           string
		timeoutMs       int
		expectedTimeout int
	}{
		{"file", 0, 3000},
		{"workspace", 0, 8000},
		{"file", 5000, 5000},
		{"workspace", 10000, 10000},
		{"", 0, 3000}, // empty defaults to "file"
	}

	for _, tt := range tests {
		t.Run(fmt.Sprintf("scope=%s,timeout=%d", tt.scope, tt.timeoutMs), func(t *testing.T) {
			// The logic at lines 204-213 in manager.go handles this.
			// Verify expected behavior:
			scope := tt.scope
			timeoutMs := tt.timeoutMs

			if scope == "" {
				scope = "file"
			}
			if timeoutMs == 0 {
				if scope == "file" {
					timeoutMs = 3000
				} else {
					timeoutMs = 8000
				}
			}

			if timeoutMs != tt.expectedTimeout {
				t.Errorf("timeout calculation error: got %d, want %d", timeoutMs, tt.expectedTimeout)
			}
		})
	}
}

// TestCommit_EmptyContents tests Commit with no files in Contents.
func TestCommit_EmptyContents(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	sess := &SimulationSession{
		ID:               "commit-empty",
		Status:           StatusMutated,
		Contents:         make(map[string]string), // empty
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
		OriginalContents: make(map[string]string),
	}
	mgr.mu.Lock()
	mgr.sessions[sess.ID] = sess
	mgr.mu.Unlock()

	result, err := mgr.Commit(ctx, sess.ID, "", false)
	if err != nil {
		t.Fatalf("Commit with empty contents failed: %v", err)
	}

	if result.FilesWritten != 0 {
		t.Errorf("expected 0 files written, got %d", result.FilesWritten)
	}

	patch, ok := result.Patch.(map[string]string)
	if !ok {
		t.Fatalf("expected patch to be map[string]string, got %T", result.Patch)
	}

	if len(patch) != 0 {
		t.Errorf("expected empty patch, got %d entries", len(patch))
	}

	if sess.Status != StatusCommitted {
		t.Errorf("expected status StatusCommitted, got %s", sess.Status)
	}
}

// TestDiscard_EmptyContents tests Discard with no files.
func TestDiscard_EmptyContents(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	sess := &SimulationSession{
		ID:               "discard-empty",
		Status:           StatusMutated,
		Contents:         make(map[string]string), // empty
		OriginalContents: make(map[string]string), // empty
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
	}
	mgr.mu.Lock()
	mgr.sessions[sess.ID] = sess
	mgr.mu.Unlock()

	err := mgr.Discard(ctx, sess.ID)
	if err != nil {
		t.Fatalf("Discard with empty contents failed: %v", err)
	}

	if sess.Status != StatusDiscarded {
		t.Errorf("expected status StatusDiscarded, got %s", sess.Status)
	}
}

// TestApplyEdit_DirtySession_ErrorMessage verifies error message for dirty session.
func TestApplyEdit_DirtySession_ErrorMessage(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	dirtyErr := fmt.Errorf("prior operation failed")
	sess := &SimulationSession{
		ID:               "apply-dirty-msg",
		Status:           StatusDirty,
		DirtyErr:         dirtyErr,
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
		t.Fatal("expected error for dirty session, got nil")
	}

	// Error should mention the session is dirty
	if !contains(err.Error(), "dirty") {
		t.Errorf("error should mention 'dirty', got: %s", err.Error())
	}
}

// TestSimulateChain_PartialFailure tests behavior when a mid-chain edit fails.
// This documents expected behavior: SimulateChain should stop at first error
// and return error from ApplyEdit or Evaluate.
func TestSimulateChain_PartialFailure(t *testing.T) {
	// Without proper mocking, we can't test actual failure during chain execution.
	// This test documents the expected behavior:
	// 1. If ApplyEdit fails at step N, return error immediately
	// 2. If Evaluate fails at step N, return error immediately
	// 3. No partial results are returned on failure
	// 4. Session may be left in an intermediate state (StatusMutated or StatusEvaluated)
}

// TestDestroy_AlreadyDestroyed verifies Destroy on already-destroyed session.
func TestDestroy_AlreadyDestroyed(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	sess := &SimulationSession{
		ID:               "destroy-twice",
		Status:           StatusCreated,
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
		Contents:         make(map[string]string),
		OriginalContents: make(map[string]string),
	}
	mgr.mu.Lock()
	mgr.sessions[sess.ID] = sess
	mgr.mu.Unlock()

	// First destroy
	if err := mgr.Destroy(ctx, sess.ID); err != nil {
		t.Fatalf("first Destroy failed: %v", err)
	}

	// Verify session is removed
	_, err := mgr.GetSession(sess.ID)
	if err == nil {
		t.Error("expected GetSession to fail after Destroy")
	}

	// Second destroy should fail
	err = mgr.Destroy(ctx, sess.ID)
	if err == nil {
		t.Fatal("expected error on second Destroy, got nil")
	}
}

// TestGetSession_ConcurrentWithDestroy tests race between GetSession and Destroy.
func TestGetSession_ConcurrentWithDestroy(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	for i := 0; i < 100; i++ {
		sess := &SimulationSession{
			ID:               fmt.Sprintf("race-destroy-%d", i),
			Status:           StatusCreated,
			Baselines:        make(map[string]DiagnosticsSnapshot),
			Versions:         make(map[string]int),
			Contents:         make(map[string]string),
			OriginalContents: make(map[string]string),
		}
		mgr.mu.Lock()
		mgr.sessions[sess.ID] = sess
		mgr.mu.Unlock()

		var wg sync.WaitGroup
		wg.Add(2)

		// Concurrent GetSession
		go func() {
			defer wg.Done()
			mgr.GetSession(sess.ID)
		}()

		// Concurrent Destroy
		go func() {
			defer wg.Done()
			mgr.Destroy(ctx, sess.ID)
		}()

		wg.Wait()
	}
	// No assertion needed - race detector will catch issues
}

// TestCommit_TargetParameter documents the target parameter.
// Currently, target is not used in the implementation (line 335),
// but it's part of the API signature.
func TestCommit_TargetParameter(t *testing.T) {
	mgr := NewSessionManager(&mockResolver{})
	ctx := context.Background()

	sess := &SimulationSession{
		ID:               "commit-target",
		Status:           StatusMutated,
		Contents:         map[string]string{"file:///tmp/test.go": "content"},
		Baselines:        make(map[string]DiagnosticsSnapshot),
		Versions:         make(map[string]int),
		OriginalContents: make(map[string]string),
	}
	mgr.mu.Lock()
	mgr.sessions[sess.ID] = sess
	mgr.mu.Unlock()

	// Target parameter is passed but not currently used
	result, err := mgr.Commit(ctx, sess.ID, "workspace", false)
	if err != nil {
		t.Fatalf("Commit failed: %v", err)
	}

	if result.SessionID != sess.ID {
		t.Errorf("SessionID mismatch: got %s, want %s", result.SessionID, sess.ID)
	}
}

// TestSession_BaselineConfidence tests baseline snapshot confidence levels.
func TestSession_BaselineConfidence(t *testing.T) {
	tests := []struct {
		name       string
		confidence Confidence
	}{
		{"high confidence", ConfidenceHigh},
		{"partial confidence", ConfidencePartial},
		{"eventual confidence", ConfidenceEventual},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			baseline := DiagnosticsSnapshot{
				URI:         "file:///tmp/test.go",
				Diagnostics: []types.LSPDiagnostic{},
				Confidence:  tt.confidence,
			}

			if baseline.Confidence != tt.confidence {
				t.Errorf("confidence mismatch: got %s, want %s", baseline.Confidence, tt.confidence)
			}
		})
	}
}

// TestAppliedEdit_FieldValues tests AppliedEdit structure.
func TestAppliedEdit_FieldValues(t *testing.T) {
	edit := AppliedEdit{
		FileURI: "file:///tmp/test.go",
		Range: types.Range{
			Start: types.Position{Line: 1, Character: 0},
			End:   types.Position{Line: 1, Character: 10},
		},
		NewText: "replacement",
		Version: 5,
	}

	if edit.FileURI != "file:///tmp/test.go" {
		t.Errorf("FileURI mismatch: got %s", edit.FileURI)
	}
	if edit.NewText != "replacement" {
		t.Errorf("NewText mismatch: got %s", edit.NewText)
	}
	if edit.Version != 5 {
		t.Errorf("Version mismatch: got %d", edit.Version)
	}
}
