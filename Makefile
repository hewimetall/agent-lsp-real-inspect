# Lint / format / test helpers

RUST_CRATES := packages/agent-lsp-state packages/agent-lsp-git packages/agent-lsp-docker

.PHONY: fmt lint test develop check

develop:
	@set -e; for d in $(RUST_CRATES); do \
		echo "==> maturin develop $$d"; \
		(cd $$d && maturin develop); \
	done
	uv sync --extra dev

fmt:
	ruff check --fix .
	ruff format .
	@set -e; for d in $(RUST_CRATES); do (cd $$d && cargo fmt); done

lint:
	ruff check .
	@set -e; for d in $(RUST_CRATES); do \
		(cd $$d && cargo fmt -- --check); \
		(cd $$d && cargo clippy --all-targets --no-default-features -- -D warnings); \
	done

test:
	pytest -q

check: lint test
