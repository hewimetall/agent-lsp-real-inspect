# agent-lsp TypeScript runtime — typescript-language-server via TCP bridge on :3737.
# Image: ghcr.io/hewimetall/agent-lsp-typescript:latest
ARG NODE_VERSION=22
FROM node:${NODE_VERSION}-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g typescript@5.8.3 typescript-language-server \
    && test -f /usr/local/lib/node_modules/typescript/lib/tsserver.js \
    && typescript-language-server --version

COPY common/stdio_tcp_bridge.py /usr/local/bin/stdio-tcp-bridge
RUN chmod +x /usr/local/bin/stdio-tcp-bridge

WORKDIR /workspace
EXPOSE 3737

ENTRYPOINT ["python3", "/usr/local/bin/stdio-tcp-bridge", "--host", "0.0.0.0", "--port", "3737", "--"]
CMD ["typescript-language-server", "--stdio"]
