# agent-lsp C/C++ runtime — clangd via TCP↔stdio bridge on :3737.
# Image: ghcr.io/hewimetall/agent-lsp-cpp:latest
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        clangd \
        python3 \
        libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && clangd --version

COPY common/stdio_tcp_bridge.py /usr/local/bin/stdio-tcp-bridge
RUN chmod +x /usr/local/bin/stdio-tcp-bridge

WORKDIR /workspace
EXPOSE 3737

# clangd discovers compile_commands.json by walking parents of opened files.
# For large trees (e.g. Ceph) place/generate compile_commands.json under /workspace.
ENTRYPOINT ["python3", "/usr/local/bin/stdio-tcp-bridge", "--host", "0.0.0.0", "--port", "3737", "--"]
CMD ["clangd", "--background-index", "--header-insertion=never"]
