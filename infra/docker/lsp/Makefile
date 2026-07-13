# Language → image mapping matches agent_lsp.runtimes.RUNTIMES.
REGISTRY ?= ghcr.io/hewimetall
TAG ?= latest

LANGUAGES := go python typescript rust

.PHONY: all $(LANGUAGES) push push-% list

all: $(LANGUAGES)

go:
	docker build -f go/Dockerfile -t $(REGISTRY)/agent-lsp-go:$(TAG) .

python:
	docker build -f python/Dockerfile -t $(REGISTRY)/agent-lsp-python:$(TAG) .

typescript:
	docker build -f typescript/Dockerfile -t $(REGISTRY)/agent-lsp-typescript:$(TAG) .

rust:
	docker build -f rust/Dockerfile -t $(REGISTRY)/agent-lsp-rust:$(TAG) .

push: $(addprefix push-,$(LANGUAGES))

push-%:
	docker push $(REGISTRY)/agent-lsp-$*:$(TAG)

list:
	@echo "Images (REGISTRY=$(REGISTRY) TAG=$(TAG)):"
	@for lang in $(LANGUAGES); do echo "  $(REGISTRY)/agent-lsp-$$lang:$(TAG)"; done
