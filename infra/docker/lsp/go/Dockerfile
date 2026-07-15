# agent-lsp Go runtime — gopls on TCP :3737 (native listen, no stdio bridge).
# Image: ghcr.io/hewimetall/agent-lsp-go:latest
ARG GO_VERSION=1.24
FROM golang:${GO_VERSION}-bookworm

# Allow gopls to pull a newer toolchain if the module requires it.
ENV GOTOOLCHAIN=auto
RUN go install golang.org/x/tools/gopls@latest \
    && gopls version

WORKDIR /workspace
EXPOSE 3737

# Matches agent_lsp.runtimes.RUNTIMES["go"].cmd
CMD ["gopls", "serve", "-listen=0.0.0.0:3737"]
