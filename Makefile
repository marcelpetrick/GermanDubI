# GermanDubI developer command surface.
# `make check` approximates the CI pipeline locally (vision.md section 42).

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
install: ## Install backend and frontend dependencies (fake providers only)
	$(UV) sync --all-groups
	cd $(FRONTEND) && $(PNPM) install --frozen-lockfile
	cd $(E2E) && $(PNPM) install --frozen-lockfile

.PHONY: install-providers
install-providers: ## Add the real German translation and speech providers
	$(UV) sync --all-groups --extra translate --extra tts

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
	$(RUN) ruff format backend
	$(RUN) ruff check --fix backend
	cd $(FRONTEND) && $(PNPM) run format

.PHONY: lint
lint: openapi-check ## Lint backend and frontend
	$(RUN) ruff format --check backend
	$(RUN) ruff check backend
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
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find backend -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf $(FRONTEND)/dist $(E2E)/test-results $(E2E)/playwright-report

# --------------------------------------------------------------------------- gate
.PHONY: check
check: lint typecheck test ## Approximate the CI pipeline locally
	@echo "check: all gates passed"
