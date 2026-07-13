# agent-lsp TypeScript runtime — typescript-language-server via TCP bridge on :3737.
# Image: ghcr.io/hewimetall/agent-lsp-typescript:latest
ARG NODE_VERSION=22
FROM node:${NODE_VERSION}-bookworm-slim

RUN npm install -g typescript typescript-language-server \
    && typescript-language-server --version

COPY common/stdio_tcp_bridge.py /usr/local/bin/stdio-tcp-bridge
RUN chmod +x /usr/local/bin/stdio-tcp-bridge

WORKDIR /workspace
EXPOSE 3737

ENTRYPOINT ["python3", "/usr/local/bin/stdio-tcp-bridge", "--host", "0.0.0.0", "--port", "3737", "--"]
CMD ["typescript-language-server", "--stdio"]
