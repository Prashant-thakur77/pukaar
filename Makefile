# Pukaar tasks. Run from the repository root. AWS targets use your current
# AWS credentials and the stack in samconfig.toml (pukaar-dev, us-east-1).
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PY       ?= backend/.venv/bin/python
PYTHON    = $(abspath $(PY))
SAM      ?= sam
STACK_ENV = eval "$$(scripts/stack_env.sh)"

.PHONY: help install test test-backend test-frontend lint build deploy deploy-web \
        seed reset-demo it secrets local validate

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

install: ## Install backend (uv) and frontend (npm) dependencies
	cd backend && uv sync --frozen --extra dev
	cd frontend && npm ci

test: test-backend test-frontend ## Backend pytest, frontend vitest and build

test-backend:
	cd backend && $(PYTHON) -m pytest -q

test-frontend:
	cd frontend && npm test && npm run build

lint: validate ## Ruff, ESLint, SAM/cfn-lint
	ruff check backend scripts
	cd frontend && npm run lint

validate: ## Lint the SAM template offline
	$(SAM) validate --lint

build: ## Build the Lambda images (needs Docker)
	$(SAM) build

deploy: build ## Deploy the stack, then publish the web app to Amplify
	$(SAM) deploy
	$(MAKE) deploy-web

deploy-web: ## Build the front end against the stack and upload it to Amplify
	scripts/deploy_web.sh

secrets: ## Store Telegram token and random secrets in SSM, set the Telegram webhook
	scripts/put_secrets.sh

seed: ## Seed villages into the deployed table and create Cognito demo users
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.seed
	$(PYTHON) scripts/seed_users.py

reset-demo: ## Clear demo state (alerts, reports, replay) on the deployed stack
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.reset_demo

it: ## Run real approval executions against the deployed stack
	$(PYTHON) scripts/it_workflow.py

local: ## Run backend (PUKAAR_MODE=local, :8000) and Vite dev server (:5173)
	trap 'kill 0' EXIT; \
	(cd backend && PUKAAR_MODE=local PYTHONPATH=src $(PYTHON) -m uvicorn Pukaar.main:app --reload --host 127.0.0.1 --port 8000) & \
	(cd frontend && VITE_API_BASE=http://127.0.0.1:8000 npm run dev) & \
	wait
