# LSP runtime images

Build language-specific images that expose an LSP on TCP `:3737`.

Example Go Dockerfile sketch:

```dockerfile
FROM golang:1.22
RUN go install golang.org/x/tools/gopls@latest
WORKDIR /workspace
EXPOSE 3737
CMD ["gopls", "serve", "-listen=0.0.0.0:3737"]
```

Session mounts the worktree at `/workspace` via bollard binds.
