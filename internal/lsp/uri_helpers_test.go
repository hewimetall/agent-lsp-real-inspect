package lsp

import "testing"

func TestPathToFileURI_WindowsDriveLowercase(t *testing.T) {
	tests := []struct {
		input string
		want  string
	}{
		{"C:/Users/test/file.go", "file:///c:/Users/test/file.go"},
		{"D:/Source/project/main.cs", "file:///d:/Source/project/main.cs"},
		{"c:/already/lower", "file:///c:/already/lower"},
		{"/home/user/file.go", "file:///home/user/file.go"},
		{"", ""},
	}
	for _, tt := range tests {
		got := PathToFileURI(tt.input)
		if got != tt.want {
			t.Errorf("PathToFileURI(%q) = %q, want %q", tt.input, got, tt.want)
		}
	}
}

func TestNormalizeFileURI(t *testing.T) {
	tests := []struct {
		input string
		want  string
	}{
		{"file:///C:/Users/test.cs", "file:///c:/Users/test.cs"},
		{"file:///D:/Source/main.go", "file:///d:/Source/main.go"},
		{"file:///c:/already/lower", "file:///c:/already/lower"},
		{"file:///home/user/file.go", "file:///home/user/file.go"},
		{"https://example.com", "https://example.com"},
		{"", ""},
		{"file:///", "file:///"},
	}
	for _, tt := range tests {
		got := NormalizeFileURI(tt.input)
		if got != tt.want {
			t.Errorf("NormalizeFileURI(%q) = %q, want %q", tt.input, got, tt.want)
		}
	}
}
