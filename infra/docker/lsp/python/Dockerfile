# agent-lsp Python runtime — pyright-langserver via TCP↔stdio bridge on :3737.
# Multi-tag: build with --build-arg PYTHON_VERSION=3.11 and tag :3.11
# Image: ghcr.io/hewimetall/agent-lsp-python:latest|3.11|3.12|3.13|3.14
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pyright \
    && command -v pyright-langserver \
    && pyright --version

COPY common/stdio_tcp_bridge.py /usr/local/bin/stdio-tcp-bridge
RUN chmod +x /usr/local/bin/stdio-tcp-bridge

WORKDIR /workspace
EXPOSE 3737

ENTRYPOINT ["python3", "/usr/local/bin/stdio-tcp-bridge", "--host", "0.0.0.0", "--port", "3737", "--"]
CMD ["pyright-langserver", "--stdio"]
