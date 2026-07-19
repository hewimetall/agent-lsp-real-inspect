# Lint / format / test / coverage (median gates, py≠rust)

# Root maturin wheel embeds state/git/docker as Rust path-deps.
PY_RUST_CRATES := .
RUST_CRATES := . packages/agent-lsp-state packages/agent-lsp-git packages/agent-lsp-docker packages/agent-lsp-runtime-worker

.PHONY: fmt lint test develop check cov-py cov-rust cov docker-lsp runtime-worker

develop:
	uv sync --extra dev
	uv run maturin develop

runtime-worker:
	cargo build --release --manifest-path packages/agent-lsp-runtime-worker/Cargo.toml

docker-lsp:
	$(MAKE) -C infra/docker/lsp all

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

cov-py:
	./scripts/python-coverage.sh

cov-rust:
	./scripts/rust-coverage.sh

cov: cov-py cov-rust

check: lint test cov
