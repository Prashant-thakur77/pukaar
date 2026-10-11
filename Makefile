# Pukaar tasks. Run from the repository root. AWS targets use your current
# AWS credentials and the stack in samconfig.toml (pukaar-dev, us-east-1).
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PY       ?= backend/.venv/bin/python
PYTHON    = $(abspath $(PY))
SAM      ?= sam
STACK_ENV = eval "$$(scripts/stack_env.sh)"
# sam's --parameter-overrides replaces samconfig's list, so read it and add the live-push key
# expiry (now + 360 days; AppSync allows at most 365). Re-deploying extends the same key.
SAM_PARAMS     = $(shell sed -n 's/^parameter_overrides = "\(.*\)"$$/\1/p' samconfig.toml)
EVENTS_KEY_EXP = $(shell date -u -d '+360 days' +%s 2>/dev/null || date -u -v+360d +%s)

.PHONY: help install test test-backend test-frontend lint build deploy deploy-web \
        seed reset-demo drill gauge-sim gauge-provision gauge-sim-mqtt ses-verify it secrets local validate

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
	$(SAM) deploy --parameter-overrides $(SAM_PARAMS) EventsApiKeyExpires=$(EVENTS_KEY_EXP)
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

drill: ## Send a labelled drill alert to registered phones (VILLAGE=gohar LEVEL=watch)
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.drill $(or $(VILLAGE),gohar) $(or $(LEVEL),watch)

gauge-sim: ## Send a SIMULATED rising river gauge to the deployed stack (VILLAGE=gohar, FAST=1 for five readings at once)
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.gauge_sim $(or $(VILLAGE),gohar) $(if $(FAST),--fast,)

gauge-provision: ## Create the AWS IoT thing + certificate for a village gauge, key in SSM (VILLAGE=gohar, DELETE=1 to remove)
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.iot_provision $(or $(VILLAGE),gohar) $(if $(DELETE),--delete,)

gauge-sim-mqtt: ## Publish a SIMULATED rising river over MQTT (AWS IoT Core, X.509) (VILLAGE=gohar, SLOW=1 for real time)
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.gauge_sim_mqtt $(or $(VILLAGE),gohar) $(if $(SLOW),--slow,)

ses-verify: ## Ask SES to verify an address for after-action e-mail (EMAIL=you@example.com); the owner clicks the link
	@test -n "$(EMAIL)" || { echo "usage: make ses-verify EMAIL=you@example.com"; exit 2; }
	aws sesv2 create-email-identity --region $(or $(AWS_REGION),us-east-1) --email-identity "$(EMAIL)"
	@echo "SES sent a verification e-mail to $(EMAIL). Its owner must click the link in it (valid 24 hours)"
	@echo "before SES will send from or, in the sandbox, to this address. Check: aws sesv2 get-email-identity --email-identity $(EMAIL)"

it: ## Run real approval executions against the deployed stack
	$(PYTHON) scripts/it_workflow.py

local: ## Run backend (PUKAAR_MODE=local, :8000) and Vite dev server (:5173)
	trap 'kill 0' EXIT; \
	(cd backend && PUKAAR_MODE=local PYTHONPATH=src $(PYTHON) -m uvicorn Pukaar.main:app --reload --host 127.0.0.1 --port 8000) & \
	(cd frontend && VITE_API_BASE=http://127.0.0.1:8000 npm run dev) & \
	wait
