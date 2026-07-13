# agent-lsp Python runtime — pyright-langserver via TCP↔stdio bridge on :3737.
# Image: ghcr.io/hewimetall/agent-lsp-python:latest
ARG NODE_VERSION=22
FROM node:${NODE_VERSION}-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g pyright \
    && command -v pyright-langserver \
    && pyright --version

COPY common/stdio_tcp_bridge.py /usr/local/bin/stdio-tcp-bridge
RUN chmod +x /usr/local/bin/stdio-tcp-bridge

WORKDIR /workspace
EXPOSE 3737

# ENTRYPOINT keeps the bridge; bollard replaces CMD with RUNTIMES["python"].cmd
ENTRYPOINT ["python3", "/usr/local/bin/stdio-tcp-bridge", "--host", "0.0.0.0", "--port", "3737", "--"]
CMD ["pyright-langserver", "--stdio"]
