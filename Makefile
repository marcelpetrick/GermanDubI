# GermanDubI developer command surface.
# `make check` is the fast inner loop; `make pipeline` runs the full CI gate (plan.md step 7).

SHELL := /bin/bash
.DEFAULT_GOAL := help

UV      ?= uv
RUN     := $(UV) run
PNPM    ?= pnpm
FRONTEND := frontend
E2E      := e2e

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------------- setup
.PHONY: install
install: ## Lean install: no real providers. This is what CI and the gate use.
	$(UV) sync --locked --all-groups
	cd $(FRONTEND) && $(PNPM) install --frozen-lockfile
	cd $(E2E) && $(PNPM) install --frozen-lockfile

.PHONY: install-providers
install-providers: ## Add every real provider: recognition, translation, speech, separation
	$(UV) sync --locked --all-groups --extra asr --extra translate --extra tts --extra separation

.PHONY: setup
setup: install install-providers hooks ## Clean checkout to a machine that can really dub
	@$(RUN) germandubi doctor

.PHONY: hooks
hooks: ## Install the pre-commit hooks
	$(RUN) pre-commit install

# --------------------------------------------------------------------------- run
.PHONY: dev
dev: ## Run API, worker and frontend dev server together
	./scripts/dev

.PHONY: api
api: ## Run only the API process
	$(RUN) uvicorn germandubi.api.app:create_app --factory --reload --host 127.0.0.1 --port 8756

.PHONY: worker
worker: ## Run only the processing worker
	$(RUN) germandubi worker

.PHONY: doctor
doctor: ## Report the state of external tool and provider dependencies
	$(RUN) germandubi doctor

# --------------------------------------------------------------------------- quality
.PHONY: format
format: ## Auto-format backend and frontend
	$(RUN) ruff format backend scripts
	$(RUN) ruff check --fix backend scripts
	cd $(FRONTEND) && $(PNPM) run format

.PHONY: lint
lint: openapi-check ## Lint backend and frontend
	$(RUN) ruff format --check backend scripts
	$(RUN) ruff check backend scripts
	cd $(FRONTEND) && $(PNPM) run lint
	cd $(FRONTEND) && $(PNPM) exec prettier --check ../e2e

.PHONY: typecheck
typecheck: ## Static type checking, backend and frontend
	$(RUN) mypy
	cd $(FRONTEND) && $(PNPM) run typecheck
	cd $(E2E) && $(PNPM) run typecheck

# --------------------------------------------------------------------------- tests
.PHONY: test
test: test-backend test-frontend ## Run backend and frontend test suites

.PHONY: test-backend
test-backend: ## Run the whole backend suite with coverage
	$(RUN) pytest --cov --cov-report=term-missing

.PHONY: test-unit
test-unit: ## Run backend unit tests only
	$(RUN) pytest backend/tests/unit

.PHONY: test-contract
test-contract: ## Run provider contract tests
	$(RUN) pytest backend/tests/contract

.PHONY: test-integration
test-integration: ## Run API and worker integration tests
	$(RUN) pytest backend/tests/integration

.PHONY: test-real
test-real: ## Run the opt-in real-provider smoke tests (needs models, network or a GPU)
	$(RUN) pytest -m real_provider

.PHONY: test-frontend
test-frontend: ## Run frontend unit tests
	cd $(FRONTEND) && $(PNPM) run test

.PHONY: test-e2e
test-e2e: ## Run Playwright end-to-end tests against fake providers
	cd $(E2E) && $(PNPM) run test

# --------------------------------------------------------------------------- artifacts
.PHONY: openapi
openapi: ## Regenerate the OpenAPI schema and the typed frontend client
	./scripts/generate-client

.PHONY: openapi-check
openapi-check: ## Fail when the committed frontend API types are stale
	./scripts/generate-client --check

.PHONY: migrate
migrate: ## Upgrade the development database to head
	$(RUN) alembic upgrade head

.PHONY: build
build: ## Build the Python wheel and the production frontend bundle
	$(UV) build
	cd $(FRONTEND) && $(PNPM) run build

.PHONY: version
version: ## Print the VCS-derived build version
	@$(RUN) python -c "from germandubi.version import build_info; print(build_info().display)"

.PHONY: clean
clean: ## Remove build and cache artifacts
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache .hypothesis htmlcov .coverage
	find backend -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf $(FRONTEND)/dist $(E2E)/test-results $(E2E)/playwright-report
	rm -rf .benchmark

# Deliberately not in `clean`: benchmark-output holds rendered videos, which are results
# rather than build artifacts and are expensive to reproduce.
.PHONY: clean-benchmarks
clean-benchmarks: ## Remove rendered benchmark videos (not touched by `make clean`)
	rm -rf benchmark-output

# --------------------------------------------------------------------------- gate
.PHONY: check
check: lint typecheck test ## Run the quality gates only (fast inner loop)
	@echo "check: all gates passed"

.PHONY: pipeline
pipeline: ## Run the complete pipeline exactly as CI runs it
	./localPipeline.sh
