# agent-lsp Rust runtime — rust-analyzer via TCP↔stdio bridge on :3737.
# Image: ghcr.io/hewimetall/agent-lsp-rust:latest
ARG RUST_VERSION=1.83
FROM rust:${RUST_VERSION}-bookworm

RUN rustup component add rust-analyzer rustfmt clippy \
    && rust-analyzer --version

COPY common/stdio_tcp_bridge.py /usr/local/bin/stdio-tcp-bridge
RUN chmod +x /usr/local/bin/stdio-tcp-bridge \
    && apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
EXPOSE 3737

ENTRYPOINT ["python3", "/usr/local/bin/stdio-tcp-bridge", "--host", "0.0.0.0", "--port", "3737", "--"]
CMD ["rust-analyzer"]
