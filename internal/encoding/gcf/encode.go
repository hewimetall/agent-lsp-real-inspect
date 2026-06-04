package gcf

import gcfgo "github.com/blackwell-systems/gcf-go"

// Encode converts any structured data to GCF tabular format string.
// Uses gcf-go's EncodeGeneric which handles arbitrary Go values
// via reflection, producing compact text output.
// Returns an error if data is nil.
func Encode(data any) (string, error) {
	if data == nil {
		return "", nil
	}
	return gcfgo.EncodeGeneric(data), nil
}
