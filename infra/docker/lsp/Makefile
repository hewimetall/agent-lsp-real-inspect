# Language → image mapping matches agent_lsp.runtimes.RUNTIMES.
REGISTRY ?= ghcr.io/hewimetall
TAG ?= latest

LANGUAGES := go python typescript rust cpp

# Version matrices for ADR-0010 language_version tags.
PYTHON_VERSIONS ?= 3.11 3.12 3.13 3.14
GO_VERSIONS ?= 1.22 1.23 1.24
NODE_VERSIONS ?= 20 22

.PHONY: all $(LANGUAGES) push push-% list versions

all: $(LANGUAGES)

go:
	docker build -f go/Dockerfile -t $(REGISTRY)/agent-lsp-go:$(TAG) .

python:
	docker build -f python/Dockerfile -t $(REGISTRY)/agent-lsp-python:$(TAG) .

typescript:
	docker build -f typescript/Dockerfile -t $(REGISTRY)/agent-lsp-typescript:$(TAG) .

rust:
	docker build -f rust/Dockerfile -t $(REGISTRY)/agent-lsp-rust:$(TAG) .

cpp:
	docker build -f cpp/Dockerfile -t $(REGISTRY)/agent-lsp-cpp:$(TAG) .

# Build versioned tags used by ensure_runtime(language_version=…).
versions: python-versions go-versions node-versions

python-versions:
	@for v in $(PYTHON_VERSIONS); do \
	  docker build -f python/Dockerfile --build-arg PYTHON_VERSION=$$v \
	    -t $(REGISTRY)/agent-lsp-python:$$v . ; \
	done

go-versions:
	@for v in $(GO_VERSIONS); do \
	  docker build -f go/Dockerfile --build-arg GO_VERSION=$$v \
	    -t $(REGISTRY)/agent-lsp-go:$$v . ; \
	done

node-versions:
	@for v in $(NODE_VERSIONS); do \
	  docker build -f typescript/Dockerfile --build-arg NODE_VERSION=$$v \
	    -t $(REGISTRY)/agent-lsp-typescript:$$v . ; \
	done

push: $(addprefix push-,$(LANGUAGES))

push-%:
	docker push $(REGISTRY)/agent-lsp-$*:$(TAG)

list:
	@echo "Images (REGISTRY=$(REGISTRY) TAG=$(TAG)):"
	@for lang in $(LANGUAGES); do echo "  $(REGISTRY)/agent-lsp-$$lang:$(TAG)"; done
	@echo "Python versions: $(PYTHON_VERSIONS)"
	@echo "Go versions: $(GO_VERSIONS)"
	@echo "Node versions: $(NODE_VERSIONS)"
