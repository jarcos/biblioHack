# biblioHack — common dev targets
# `make help` to list everything.

.DEFAULT_GOAL := help
SHELL := /bin/bash

# ────────────────────────────────────────────────────────────
# Meta
# ────────────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} /^[a-zA-Z0-9_.-]+:.*?##/ { printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ────────────────────────────────────────────────────────────
# Dev environment
# ────────────────────────────────────────────────────────────

.PHONY: dev-up
dev-up: ## Start the full docker-compose dev stack (postgres + redis + api + frontend).
	docker compose up -d --build

.PHONY: dev-down
dev-down: ## Stop and remove the dev stack.
	docker compose down

.PHONY: dev-logs
dev-logs: ## Tail logs from the dev stack.
	docker compose logs -f

.PHONY: dev-ps
dev-ps: ## Show running dev containers.
	docker compose ps

.PHONY: dev-nuke
dev-nuke: ## Stop dev stack AND wipe volumes. Destroys local data.
	docker compose down -v

# ────────────────────────────────────────────────────────────
# Backend
# ────────────────────────────────────────────────────────────

.PHONY: backend-install
backend-install: ## Install backend deps via uv.
	cd backend && uv sync --all-extras

.PHONY: scraper-install-browsers
scraper-install-browsers: ## Download Camoufox + Patchright Chromium binaries (one-off, ~600MB).
	cd backend && uv sync --extra scraper
	# Camoufox: Firefox-based stealth browser used by some Scrapling fetchers.
	cd backend && uv run camoufox fetch
	# Patchright: Chromium-based stealth browser. Scrapling 0.4.x's
	# StealthyFetcher transitively imports it even though it's a Firefox
	# fetcher; the import chain pulls Chromium in, so it must be installed.
	cd backend && uv run patchright install chromium

.PHONY: backend-lint
backend-lint: ## Lint the backend with ruff.
	cd backend && uv run ruff check .

.PHONY: backend-format
backend-format: ## Format the backend with ruff.
	cd backend && uv run ruff format .

.PHONY: backend-typecheck
backend-typecheck: ## Typecheck the backend with mypy.
	cd backend && uv run mypy src

.PHONY: backend-test
backend-test: ## Run backend tests with pytest.
	cd backend && uv run pytest

.PHONY: backend-check
backend-check: backend-lint backend-typecheck backend-test ## Lint + typecheck + test.

.PHONY: backend-run
backend-run: ## Run the FastAPI app locally (without docker).
	cd backend && uv run uvicorn bibliohack.interfaces.http.app:app --reload --host 0.0.0.0 --port 8000

.PHONY: probe-titn
probe-titn: ## Probe the upstream OPAC for the highest known TITN. Requires `make scraper-install-browsers` first.
	cd backend && uv sync --extra scraper >/dev/null && uv run bibliohack catalog probe-titn-range

.PHONY: seed-titn
seed-titn: ## Seed scrape_tasks with the [1..N] range. Usage: make seed-titn HIGH=1500000
	@if [ -z "$(HIGH)" ]; then echo "Usage: make seed-titn HIGH=<max_titn> [LOW=1]"; exit 2; fi
	cd backend && uv run bibliohack catalog seed --from $${LOW:-1} --to $(HIGH)

# ────────────────────────────────────────────────────────────
# Database migrations (Alembic)
# ────────────────────────────────────────────────────────────

.PHONY: db-upgrade
db-upgrade: ## Apply all pending Alembic migrations (uses DATABASE_URL_SYNC if set).
	cd backend && uv run alembic upgrade head

.PHONY: db-downgrade
db-downgrade: ## Roll back one migration.
	cd backend && uv run alembic downgrade -1

.PHONY: db-revision
db-revision: ## Generate a new auto-migration. Usage: make db-revision MSG="describe change"
	cd backend && uv run alembic revision --autogenerate -m "$(MSG)"

.PHONY: db-current
db-current: ## Show the current applied revision.
	cd backend && uv run alembic current

.PHONY: db-history
db-history: ## Show migration history.
	cd backend && uv run alembic history --verbose

# ────────────────────────────────────────────────────────────
# Frontend
# ────────────────────────────────────────────────────────────

.PHONY: frontend-install
frontend-install: ## Install frontend deps via pnpm.
	cd frontend && pnpm install

.PHONY: frontend-lint
frontend-lint: ## Lint the frontend.
	cd frontend && pnpm lint

.PHONY: frontend-format
frontend-format: ## Format the frontend with prettier.
	cd frontend && pnpm format

.PHONY: frontend-typecheck
frontend-typecheck: ## Typecheck the frontend (astro check + tsc).
	cd frontend && pnpm typecheck

.PHONY: frontend-test
frontend-test: ## Run frontend unit tests with vitest.
	cd frontend && pnpm test

.PHONY: frontend-check
frontend-check: frontend-lint frontend-typecheck frontend-test ## Lint + typecheck + test.

.PHONY: frontend-run
frontend-run: ## Run the Astro dev server.
	cd frontend && pnpm dev

# ────────────────────────────────────────────────────────────
# Aggregate
# ────────────────────────────────────────────────────────────

.PHONY: install
install: backend-install frontend-install ## Install all deps.

.PHONY: check
check: backend-check frontend-check ## Lint + typecheck + test everything.

.PHONY: format
format: backend-format frontend-format ## Format everything.

.PHONY: precommit
precommit: ## Run pre-commit on all files.
	cd backend && uv run pre-commit run --all-files
