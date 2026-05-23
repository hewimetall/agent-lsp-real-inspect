package config_test

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/blackwell-systems/agent-lsp/internal/config"
)

func TestParseArgs_Legacy(t *testing.T) {
	// Create a temporary fake binary so os.Stat passes.
	tmp := t.TempDir()
	bin := filepath.Join(tmp, "gopls")
	if err := os.WriteFile(bin, []byte("#!/bin/sh"), 0755); err != nil {
		t.Fatal(err)
	}

	result, err := config.ParseArgs([]string{"go", bin})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if !result.IsSingleServer {
		t.Error("expected IsSingleServer=true")
	}
	if result.LanguageID != "go" {
		t.Errorf("expected LanguageID=go, got %q", result.LanguageID)
	}
	if result.ServerPath != bin {
		t.Errorf("expected ServerPath=%q, got %q", bin, result.ServerPath)
	}
	if len(result.ServerArgs) != 0 {
		t.Errorf("expected no ServerArgs, got %v", result.ServerArgs)
	}
}

func TestParseArgs_MultiArg(t *testing.T) {
	result, err := config.ParseArgs([]string{
		"go:gopls",
		"typescript:typescript-language-server,--stdio",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Config == nil {
		t.Fatal("expected Config to be set")
	}
	if len(result.Config.Servers) != 2 {
		t.Fatalf("expected 2 servers, got %d", len(result.Config.Servers))
	}

	goEntry := result.Config.Servers[0]
	if len(goEntry.Extensions) != 1 || goEntry.Extensions[0] != "go" {
		t.Errorf("expected go extensions=[go], got %v", goEntry.Extensions)
	}

	tsEntry := result.Config.Servers[1]
	if len(tsEntry.Extensions) != 2 {
		t.Errorf("expected typescript extensions=[ts,tsx], got %v", tsEntry.Extensions)
	}
	foundTS, foundTSX := false, false
	for _, ext := range tsEntry.Extensions {
		if ext == "ts" {
			foundTS = true
		}
		if ext == "tsx" {
			foundTSX = true
		}
	}
	if !foundTS || !foundTSX {
		t.Errorf("expected ts and tsx in extensions, got %v", tsEntry.Extensions)
	}
}

func TestParseArgs_ConfigFlag(t *testing.T) {
	tmp := t.TempDir()
	cfgPath := filepath.Join(tmp, "lsp-mcp.json")

	cfg := config.Config{
		Servers: []config.ServerEntry{
			{Extensions: []string{"go"}, Command: []string{"gopls"}},
			{Extensions: []string{"ts", "tsx"}, Command: []string{"typescript-language-server", "--stdio"}},
		},
	}
	data, err := json.Marshal(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(cfgPath, data, 0644); err != nil {
		t.Fatal(err)
	}

	result, err := config.ParseArgs([]string{"--config", cfgPath})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Config == nil {
		t.Fatal("expected Config to be set")
	}
	if len(result.Config.Servers) != 2 {
		t.Fatalf("expected 2 servers, got %d", len(result.Config.Servers))
	}
	if result.Config.Servers[0].Extensions[0] != "go" {
		t.Errorf("expected first server extension=go, got %v", result.Config.Servers[0].Extensions)
	}
}

func TestParseArgs_AutoEmpty(t *testing.T) {
	// NOTE: This test requires at least one language server in PATH to pass.
	// If no servers are found, AutodetectServers() will return an error.
	result, err := config.ParseArgs([]string{})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Config == nil {
		t.Fatal("expected Config to be set")
	}
	if len(result.Config.Servers) == 0 {
		t.Error("expected at least one server found via auto-detect")
	}
	if result.IsSingleServer {
		t.Error("expected IsSingleServer=false for auto-detect mode")
	}
}

func TestParseArgs_AutoFlag(t *testing.T) {
	// NOTE: This test requires at least one language server in PATH to pass.
	// If no servers are found, AutodetectServers() will return an error.
	result, err := config.ParseArgs([]string{"--auto"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if result.Config == nil {
		t.Fatal("expected Config to be set")
	}
	if len(result.Config.Servers) == 0 {
		t.Error("expected at least one server found via auto-detect")
	}
	if result.IsSingleServer {
		t.Error("expected IsSingleServer=false for auto-detect mode")
	}
}

func TestLoadConfig_Valid(t *testing.T) {
	tmp := t.TempDir()
	cfgPath := filepath.Join(tmp, "config.json")

	data := `{"servers":[{"extensions":["go"],"command":["gopls"]}]}`
	if err := os.WriteFile(cfgPath, []byte(data), 0644); err != nil {
		t.Fatal(err)
	}

	cfg, err := config.LoadConfig(cfgPath)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(cfg.Servers) != 1 {
		t.Fatalf("expected 1 server, got %d", len(cfg.Servers))
	}
	if len(cfg.Servers[0].Extensions) != 1 || cfg.Servers[0].Extensions[0] != "go" {
		t.Errorf("expected Extensions=[go], got %v", cfg.Servers[0].Extensions)
	}
}

func TestLoadConfig_Missing(t *testing.T) {
	_, err := config.LoadConfig("/nonexistent/path/config.json")
	if err == nil {
		t.Error("expected error for nonexistent config file, got nil")
	}
}

// TestParseArgs_HTTPFlags tests the HTTP transport flags.
func TestParseArgs_HTTPFlags(t *testing.T) {
	tests := []struct {
		name        string
		args        []string
		wantHTTP    bool
		wantPort    int
		wantAddr    string
		wantNoAuth  bool
		wantToken   string
		wantErr     bool
		errContains string
	}{
		{
			name:     "http mode enabled",
			args:     []string{"--http", "go:gopls"},
			wantHTTP: true,
			wantPort: 8080,
			wantAddr: "127.0.0.1",
		},
		{
			name:     "custom port",
			args:     []string{"--http", "--port", "9000", "go:gopls"},
			wantHTTP: true,
			wantPort: 9000,
			wantAddr: "127.0.0.1",
		},
		{
			name:     "custom listen address",
			args:     []string{"--http", "--listen-addr", "0.0.0.0", "go:gopls"},
			wantHTTP: true,
			wantPort: 8080,
			wantAddr: "0.0.0.0",
		},
		{
			name:       "no-auth flag",
			args:       []string{"--http", "--no-auth", "go:gopls"},
			wantHTTP:   true,
			wantPort:   8080,
			wantAddr:   "127.0.0.1",
			wantNoAuth: true,
		},
		{
			name:      "token flag",
			args:      []string{"--http", "--token", "secret123", "go:gopls"},
			wantHTTP:  true,
			wantPort:  8080,
			wantAddr:  "127.0.0.1",
			wantToken: "secret123",
		},
		{
			name:        "port without value",
			args:        []string{"--port"},
			wantErr:     true,
			errContains: "--port requires a value",
		},
		{
			name:        "port invalid integer",
			args:        []string{"--port", "abc"},
			wantErr:     true,
			errContains: "not a valid integer",
		},
		{
			name:        "port out of range low",
			args:        []string{"--port", "0"},
			wantErr:     true,
			errContains: "out of range",
		},
		{
			name:        "port out of range high",
			args:        []string{"--port", "65536"},
			wantErr:     true,
			errContains: "out of range",
		},
		{
			name:        "listen-addr without value",
			args:        []string{"--listen-addr"},
			wantErr:     true,
			errContains: "--listen-addr requires a value",
		},
		{
			name:        "listen-addr invalid IP",
			args:        []string{"--listen-addr", "invalid-ip"},
			wantErr:     true,
			errContains: "not a valid IP address",
		},
		{
			name:        "token without value",
			args:        []string{"--token"},
			wantErr:     true,
			errContains: "--token requires a value",
		},
		{
			name:        "audit-log without value",
			args:        []string{"--audit-log"},
			wantErr:     true,
			errContains: "--audit-log requires a value",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Clear any existing env var
			oldToken := os.Getenv("AGENT_LSP_TOKEN")
			os.Unsetenv("AGENT_LSP_TOKEN")
			defer func() {
				if oldToken != "" {
					os.Setenv("AGENT_LSP_TOKEN", oldToken)
				}
			}()

			result, err := config.ParseArgs(tt.args)
			if tt.wantErr {
				if err == nil {
					t.Fatalf("expected error containing %q, got nil", tt.errContains)
				}
				if tt.errContains != "" && !containsString(err.Error(), tt.errContains) {
					t.Errorf("expected error containing %q, got %q", tt.errContains, err.Error())
				}
				return
			}

			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}

			if result.HTTPMode != tt.wantHTTP {
				t.Errorf("HTTPMode: got %v, want %v", result.HTTPMode, tt.wantHTTP)
			}
			if result.HTTPPort != tt.wantPort {
				t.Errorf("HTTPPort: got %d, want %d", result.HTTPPort, tt.wantPort)
			}
			if result.HTTPListenAddr != tt.wantAddr {
				t.Errorf("HTTPListenAddr: got %q, want %q", result.HTTPListenAddr, tt.wantAddr)
			}
			if result.HTTPNoAuth != tt.wantNoAuth {
				t.Errorf("HTTPNoAuth: got %v, want %v", result.HTTPNoAuth, tt.wantNoAuth)
			}
			if tt.wantToken != "" && result.HTTPToken != tt.wantToken {
				t.Errorf("HTTPToken: got %q, want %q", result.HTTPToken, tt.wantToken)
			}
		})
	}
}

// TestParseArgs_TokenEnvVar tests that AGENT_LSP_TOKEN env var overrides --token flag.
func TestParseArgs_TokenEnvVar(t *testing.T) {
	// Set env var
	oldToken := os.Getenv("AGENT_LSP_TOKEN")
	os.Setenv("AGENT_LSP_TOKEN", "env-token")
	defer func() {
		if oldToken != "" {
			os.Setenv("AGENT_LSP_TOKEN", oldToken)
		} else {
			os.Unsetenv("AGENT_LSP_TOKEN")
		}
	}()

	// Pass --token flag but env var should win
	result, err := config.ParseArgs([]string{"--token", "flag-token", "go:gopls"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if result.HTTPToken != "env-token" {
		t.Errorf("expected token from env var (env-token), got %q", result.HTTPToken)
	}
}

// TestParseArgs_AuditLog tests the --audit-log flag.
func TestParseArgs_AuditLog(t *testing.T) {
	result, err := config.ParseArgs([]string{"--audit-log", "/tmp/audit.log", "go:gopls"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if result.AuditLogPath != "/tmp/audit.log" {
		t.Errorf("expected AuditLogPath=/tmp/audit.log, got %q", result.AuditLogPath)
	}
}

// TestParseArgs_ConfigMissingPath tests --config without a path argument.
func TestParseArgs_ConfigMissingPath(t *testing.T) {
	_, err := config.ParseArgs([]string{"--config"})
	if err == nil {
		t.Fatal("expected error for --config without path")
	}
	if !containsString(err.Error(), "--config requires a file path argument") {
		t.Errorf("unexpected error message: %v", err)
	}
}

// TestParseArgs_LegacyMissingBinary tests legacy mode when binary is missing.
func TestParseArgs_LegacyMissingBinary(t *testing.T) {
	_, err := config.ParseArgs([]string{"go", "/nonexistent/gopls"})
	if err == nil {
		t.Fatal("expected error for missing binary")
	}
	if !containsString(err.Error(), "not found") {
		t.Errorf("unexpected error message: %v", err)
	}
}

// TestParseArgs_MultiArgInvalid tests invalid multi-arg format.
func TestParseArgs_MultiArgInvalid(t *testing.T) {
	tests := []struct {
		name        string
		args        []string
		errContains string
	}{
		{
			name:        "missing colon",
			args:        []string{"gopls"},
			errContains: "expected format language-id:binary",
		},
		{
			name:        "empty binary",
			args:        []string{"go:"},
			errContains: "binary path is empty",
		},
		{
			name:        "colon but no binary",
			args:        []string{"go:,"},
			errContains: "binary path is empty",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := config.ParseArgs(tt.args)
			if err == nil {
				t.Fatal("expected error")
			}
			if !containsString(err.Error(), tt.errContains) {
				t.Errorf("expected error containing %q, got %q", tt.errContains, err.Error())
			}
		})
	}
}

// TestParseArgs_MultiArgUnknownLanguage tests multi-arg with unknown language ID.
func TestParseArgs_MultiArgUnknownLanguage(t *testing.T) {
	// Unknown language IDs should default to using the language ID as the extension
	result, err := config.ParseArgs([]string{"unknown-lang:mylangserver"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if result.Config == nil || len(result.Config.Servers) != 1 {
		t.Fatal("expected 1 server entry")
	}

	entry := result.Config.Servers[0]
	if len(entry.Extensions) != 1 || entry.Extensions[0] != "unknown-lang" {
		t.Errorf("expected extension [unknown-lang], got %v", entry.Extensions)
	}
}

// TestLoadConfig_InvalidJSON tests config file with malformed JSON.
func TestLoadConfig_InvalidJSON(t *testing.T) {
	tmp := t.TempDir()
	cfgPath := filepath.Join(tmp, "bad.json")

	// Write malformed JSON
	if err := os.WriteFile(cfgPath, []byte("{invalid json}"), 0644); err != nil {
		t.Fatal(err)
	}

	_, err := config.LoadConfig(cfgPath)
	if err == nil {
		t.Fatal("expected error for invalid JSON")
	}
	if !containsString(err.Error(), "parse config") {
		t.Errorf("unexpected error message: %v", err)
	}
}

// TestLoadConfig_EmptyFile tests config file that is empty.
func TestLoadConfig_EmptyFile(t *testing.T) {
	tmp := t.TempDir()
	cfgPath := filepath.Join(tmp, "empty.json")

	if err := os.WriteFile(cfgPath, []byte(""), 0644); err != nil {
		t.Fatal(err)
	}

	_, err := config.LoadConfig(cfgPath)
	if err == nil {
		t.Fatal("expected error for empty config file")
	}
}

// TestLoadConfig_MissingServersField tests config without servers field.
func TestLoadConfig_MissingServersField(t *testing.T) {
	tmp := t.TempDir()
	cfgPath := filepath.Join(tmp, "no-servers.json")

	// Valid JSON but missing servers field
	if err := os.WriteFile(cfgPath, []byte("{}"), 0644); err != nil {
		t.Fatal(err)
	}

	cfg, err := config.LoadConfig(cfgPath)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Should parse successfully with empty servers array
	if cfg.Servers == nil {
		cfg.Servers = []config.ServerEntry{}
	}
	if len(cfg.Servers) != 0 {
		t.Errorf("expected 0 servers, got %d", len(cfg.Servers))
	}
}

// TestLoadConfig_ExtraFields tests config with extra unknown fields (should be ignored).
func TestLoadConfig_ExtraFields(t *testing.T) {
	tmp := t.TempDir()
	cfgPath := filepath.Join(tmp, "extra.json")

	data := `{
		"servers": [{"extensions":["go"],"command":["gopls"]}],
		"unknown_field": "should be ignored",
		"another_field": 123
	}`
	if err := os.WriteFile(cfgPath, []byte(data), 0644); err != nil {
		t.Fatal(err)
	}

	cfg, err := config.LoadConfig(cfgPath)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(cfg.Servers) != 1 {
		t.Fatalf("expected 1 server, got %d", len(cfg.Servers))
	}
}

// TestLoadConfig_InvalidServerEntry tests config with invalid server entry structure.
func TestLoadConfig_InvalidServerEntry(t *testing.T) {
	tests := []struct {
		name string
		json string
	}{
		{
			name: "extensions is not an array",
			json: `{"servers":[{"extensions":"go","command":["gopls"]}]}`,
		},
		{
			name: "command is not an array",
			json: `{"servers":[{"extensions":["go"],"command":"gopls"}]}`,
		},
		{
			name: "servers is not an array",
			json: `{"servers":"not-an-array"}`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tmp := t.TempDir()
			cfgPath := filepath.Join(tmp, "invalid.json")

			if err := os.WriteFile(cfgPath, []byte(tt.json), 0644); err != nil {
				t.Fatal(err)
			}

			_, err := config.LoadConfig(cfgPath)
			if err == nil {
				t.Fatal("expected error for invalid server entry")
			}
		})
	}
}

// TestLoadConfig_UnicodeContent tests config with unicode content.
func TestLoadConfig_UnicodeContent(t *testing.T) {
	tmp := t.TempDir()
	cfgPath := filepath.Join(tmp, "unicode.json")

	// Config with unicode in language_id (edge case)
	data := `{"servers":[{"extensions":["go"],"command":["gopls"],"language_id":"go🎉"}]}`
	if err := os.WriteFile(cfgPath, []byte(data), 0644); err != nil {
		t.Fatal(err)
	}

	cfg, err := config.LoadConfig(cfgPath)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(cfg.Servers) != 1 {
		t.Fatalf("expected 1 server, got %d", len(cfg.Servers))
	}
	if cfg.Servers[0].LanguageID != "go🎉" {
		t.Errorf("expected language_id with emoji, got %q", cfg.Servers[0].LanguageID)
	}
}

// TestLoadConfig_LargeConfig tests config with many servers.
func TestLoadConfig_LargeConfig(t *testing.T) {
	tmp := t.TempDir()
	cfgPath := filepath.Join(tmp, "large.json")

	// Generate config with 50 servers
	var servers []string
	for i := 0; i < 50; i++ {
		servers = append(servers, fmt.Sprintf(`{"extensions":["ext%d"],"command":["server%d"]}`, i, i))
	}
	data := fmt.Sprintf(`{"servers":[%s]}`, strings.Join(servers, ","))

	if err := os.WriteFile(cfgPath, []byte(data), 0644); err != nil {
		t.Fatal(err)
	}

	cfg, err := config.LoadConfig(cfgPath)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(cfg.Servers) != 50 {
		t.Fatalf("expected 50 servers, got %d", len(cfg.Servers))
	}
}

// TestLoadConfig_NullValues tests config with null values.
func TestLoadConfig_NullValues(t *testing.T) {
	tmp := t.TempDir()
	cfgPath := filepath.Join(tmp, "null.json")

	data := `{"servers":[{"extensions":["go"],"command":["gopls"],"language_id":null}]}`
	if err := os.WriteFile(cfgPath, []byte(data), 0644); err != nil {
		t.Fatal(err)
	}

	cfg, err := config.LoadConfig(cfgPath)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(cfg.Servers) != 1 {
		t.Fatalf("expected 1 server, got %d", len(cfg.Servers))
	}
	if cfg.Servers[0].LanguageID != "" {
		t.Errorf("expected empty language_id, got %q", cfg.Servers[0].LanguageID)
	}
}

// TestParseArgs_LegacyWithArgs tests legacy mode with server arguments.
func TestParseArgs_LegacyWithArgs(t *testing.T) {
	tmp := t.TempDir()
	bin := filepath.Join(tmp, "tsserver")
	if err := os.WriteFile(bin, []byte("#!/bin/sh"), 0755); err != nil {
		t.Fatal(err)
	}

	result, err := config.ParseArgs([]string{"typescript", bin, "--stdio", "--verbose"})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if !result.IsSingleServer {
		t.Error("expected IsSingleServer=true")
	}
	if result.LanguageID != "typescript" {
		t.Errorf("expected LanguageID=typescript, got %q", result.LanguageID)
	}
	if len(result.ServerArgs) != 2 {
		t.Fatalf("expected 2 args, got %d", len(result.ServerArgs))
	}
	if result.ServerArgs[0] != "--stdio" || result.ServerArgs[1] != "--verbose" {
		t.Errorf("unexpected args: %v", result.ServerArgs)
	}
}

// TestParseArgs_MultiArgWithMultipleArgs tests multi-arg with comma-separated args.
func TestParseArgs_MultiArgWithMultipleArgs(t *testing.T) {
	result, err := config.ParseArgs([]string{
		"go:gopls,-v,-rpc.trace",
		"python:pyright-langserver,--stdio,--verbose",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if len(result.Config.Servers) != 2 {
		t.Fatalf("expected 2 servers, got %d", len(result.Config.Servers))
	}

	// Check go server
	goEntry := result.Config.Servers[0]
	if len(goEntry.Command) != 3 {
		t.Fatalf("expected 3 command parts for go, got %d", len(goEntry.Command))
	}
	if goEntry.Command[1] != "-v" || goEntry.Command[2] != "-rpc.trace" {
		t.Errorf("unexpected go command args: %v", goEntry.Command)
	}

	// Check python server
	pyEntry := result.Config.Servers[1]
	if len(pyEntry.Command) != 3 {
		t.Fatalf("expected 3 command parts for python, got %d", len(pyEntry.Command))
	}
	if pyEntry.Command[1] != "--stdio" || pyEntry.Command[2] != "--verbose" {
		t.Errorf("unexpected python command args: %v", pyEntry.Command)
	}
}

// containsString checks if a string contains a substring.
func containsString(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(substr) == 0 ||
		(len(s) > 0 && len(substr) > 0 && strings.Contains(s, substr)))
}
