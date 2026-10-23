# Pukaar tasks. Run from the repository root. AWS targets use your current AWS credentials and
# the stack of STAGE in samconfig.toml: dev (default) is pukaar-dev in us-east-1, STAGE=prod is
# pukaar-prod in ap-south-1 (docs/DEPLOY.md, "Production stage").
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PY       ?= backend/.venv/bin/python
PYTHON    = $(abspath $(PY))
SAM      ?= sam
STAGE    ?= dev
# samconfig.toml section for the stage: [default.*] is dev, [prod.*] is prod.
SAM_ENV   = $(if $(filter dev,$(STAGE)),default,$(STAGE))
# One value from samconfig.toml: $(call samconfig,<section>,<key>)
samconfig = $(shell awk -v s='[$(SAM_ENV).$(1).parameters]' '/^\[/{on=($$0==s)} on && index($$0,"$(2) = \"")==1{v=substr($$0,length("$(2) = \"")+1); sub(/"$$/,"",v); print v}' samconfig.toml)
STACK     = $(call samconfig,global,stack_name)
REGION    = $(call samconfig,global,region)
# Every AWS script and the stack outputs (scripts/stack_env.sh) follow the stage.
export PUKAAR_STACK = $(STACK)
export AWS_REGION   = $(REGION)
STACK_ENV = eval "$$(scripts/stack_env.sh)"
# sam's --parameter-overrides replaces samconfig's list, so read it and add the live-push key
# expiry (now + 360 days; AppSync allows at most 365). Re-deploying extends the same key.
SAM_PARAMS     = $(call samconfig,deploy,parameter_overrides)
EVENTS_KEY_EXP = $(shell date -u -d '+360 days' +%s 2>/dev/null || date -u -v+360d +%s)
# Kept out of git, in .env.deploy.local (every stage) and .env.deploy.<stage>.local (that stage; wins):
#   ALARM_EMAIL=<on-call address>          subscribed to the alarm topic (confirm the e-mail SNS sends)
#   AFTER_ACTION_FROM=<SES-verified sender> optional after-action e-mail
#   VOICE_PROVIDER=exotel|plivo|off        voice calls (docs/VOICE.md); EXOTEL_API_HOST for a Mumbai account
#   CAP_SENDER=<authority id>              CAP <sender>, e.g. the DDMA's e-mail (required for STAGE=prod)
#   CAP_SENDER_NAME=<authority name>       CAP <senderName> in English (required for STAGE=prod)
#   CAP_SENDER_NAME_HI=<name in Hindi>     CAP <senderName> in Hindi (optional)
#   WEB_ORIGIN=https://<host>              the web app's own domain, when not the Amplify URL
#   EDGE_WEB_ACL_ARN=<arn>                 prod only: the web ACL from make waf-edge (CloudFront + AWS WAF on the API)
-include .env.deploy.local
-include .env.deploy.$(STAGE).local
# Names hold spaces and commas: each goes to sam as one quoted Key="value".
DEPLOY_EXTRA   = $(if $(ALARM_EMAIL),AlarmEmail=$(ALARM_EMAIL)) \
                 $(if $(AFTER_ACTION_FROM),AfterActionFrom=$(AFTER_ACTION_FROM)) \
                 $(if $(VOICE_PROVIDER),VoiceProvider=$(VOICE_PROVIDER)) \
                 $(if $(EXOTEL_API_HOST),ExotelApiHost=$(EXOTEL_API_HOST)) \
                 $(if $(WEB_ORIGIN),WebOrigin=$(WEB_ORIGIN)) \
                 $(if $(EDGE_WEB_ACL_ARN),EdgeWebAclArn=$(EDGE_WEB_ACL_ARN)) \
                 $(if $(CAP_SENDER),CapSender=$(CAP_SENDER)) \
                 $(if $(CAP_SENDER_NAME),'CapSenderName="$(CAP_SENDER_NAME)"') \
                 $(if $(CAP_SENDER_NAME_HI),'CapSenderNameHi="$(CAP_SENDER_NAME_HI)"')

.PHONY: help install test test-backend test-frontend lint build deploy deploy-web \
        seed reset-demo demo-open demo-reset drill add-village staff-assign waf-edge restore-drill voice-add recipient-role voice-list voice-remove voice-urls officer-phone gauge-sim gauge-provision gauge-sim-mqtt device-provision siren-sim protocol-vectors ses-verify it secrets vapid-keys local validate smoke

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
	$(SAM) build --config-env $(SAM_ENV)

deploy: build ## Deploy the stack of STAGE (dev, or prod), then publish the web app to Amplify (set ALARM_EMAIL in .env.deploy.local)
	@test -n "$(STACK)" -a -n "$(SAM_PARAMS)" || { echo "No [$(SAM_ENV).*] settings for STAGE=$(STAGE) in samconfig.toml." >&2; exit 2; }
	@test -n "$(ALARM_EMAIL)" || echo "WARNING: ALARM_EMAIL is not set in .env.deploy.local: CloudWatch alarms will notify nobody." >&2
	@if [ "$(STAGE)" = prod ]; then \
	  test -n "$(ALARM_EMAIL)" || { echo "STAGE=prod needs ALARM_EMAIL (.env.deploy.prod.local): alarms must reach someone." >&2; exit 2; }; \
	  test -n "$(CAP_SENDER)" -a -n "$(CAP_SENDER_NAME)" || { echo "STAGE=prod needs CAP_SENDER and CAP_SENDER_NAME, the issuing authority's (.env.deploy.prod.local)." >&2; exit 2; }; \
	  case "$(CAP_SENDER_NAME)" in *"(demo)"*) echo "STAGE=prod: CAP_SENDER_NAME must be the authority's name, not the demo one." >&2; exit 2;; esac; \
	fi
	$(SAM) deploy --config-env $(SAM_ENV) --parameter-overrides $(SAM_PARAMS) EventsApiKeyExpires=$(EVENTS_KEY_EXP) $(DEPLOY_EXTRA)
	$(MAKE) deploy-web

waf-edge: ## Prod only: the AWS WAF web ACL for CloudFront in front of the API, in us-east-1 (prints its ARN for EDGE_WEB_ACL_ARN)
	@test "$(STAGE)" = prod || { echo "waf-edge is for STAGE=prod: AWS WAF bills by the month, so dev has none." >&2; exit 2; }
	aws cloudformation deploy --region us-east-1 --stack-name pukaar-$(STAGE)-waf-edge \
	  --template-file infra/waf-edge.yaml --parameter-overrides Stage=$(STAGE) --no-fail-on-empty-changeset
	scripts/edge_secret.sh
	@echo "EDGE_WEB_ACL_ARN=$$(aws cloudformation describe-stacks --region us-east-1 --stack-name pukaar-$(STAGE)-waf-edge \
	  --query "Stacks[0].Outputs[?OutputKey=='WebAclArn'].OutputValue" --output text)   (put it in .env.deploy.prod.local)"

restore-drill: ## Restore the table from point-in-time recovery into a scratch table, compare counts, delete it (AT=<ISO UTC>, KEEP=1)
	$(PYTHON) scripts/restore_drill.py --stage $(STAGE) --region $(REGION) $(if $(AT),--at $(AT)) $(if $(KEEP),--keep)

deploy-web: ## Build the front end against the stack and upload it to Amplify
	scripts/deploy_web.sh

secrets: ## Store Telegram token and random secrets in SSM, set the Telegram webhook
	scripts/put_secrets.sh

vapid-keys: ## Make the Web Push (VAPID) key pair in SSM, private key never shown (ROTATE=1 to replace it)
	cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.vapid_keys $(if $(ROTATE),--rotate,)

seed: ## Seed villages into the deployed table and create Cognito demo users (villages only for STAGE=prod)
	$(STACK_ENV); cd backend && PUKAAR_STAGE=$(STAGE) PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.seed
	@if [ "$(STAGE)" = prod ]; then echo "STAGE=prod: no demo or judge users. Add each officer and pradhan by hand (docs/DEPLOY.md, \"Production stage\")."; \
	else $(PYTHON) scripts/seed_users.py; fi

reset-demo: ## Clear demo state (alerts, reports, replay) on the deployed stack (refused for STAGE=prod)
	@test "$(STAGE)" != prod || { echo "reset-demo deletes alerts and reports: never on STAGE=prod." >&2; exit 2; }
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.reset_demo

demo-open: ## Live jury demo: open it (or rotate the join code); prints the presenter URL, the code and the QR link (docs/DEMO_LIVE.md)
	$(STACK_ENV); cd backend && PUKAAR_STAGE=$(STAGE) PUKAAR_WEB_URL="$$STACK_WebUrl" PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.demo open

demo-reset: ## Live jury demo: erase every demo person and demo alert now (the code stops working)
	$(STACK_ENV); cd backend && PUKAAR_STAGE=$(STAGE) PUKAAR_WEB_URL="$$STACK_WebUrl" PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.demo reset

drill: ## Send a labelled drill alert to registered phones (VILLAGE=gohar LEVEL=watch CHANNEL=all|telegram|voice)
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.drill $(or $(VILLAGE),gohar) $(or $(LEVEL),watch) $(or $(CHANNEL),all)

voice-add: ## Register a consented voice number (VILLAGE= NAME= PHONE=+91.. CONSENT="verbal, 2026-10-25"; ROLE=pradhan, CHAT= for Telegram too)
	@test -n "$(VILLAGE)" -a -n "$(NAME)" -a -n "$(PHONE)" -a -n "$(CONSENT)" || { echo 'usage: make voice-add VILLAGE=gohar NAME="Asha Devi" PHONE=+919812345678 CONSENT="verbal, field visit 2026-10-25"'; exit 2; }
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.voice add "$(VILLAGE)" "$(NAME)" "$(PHONE)" "$(CONSENT)" "$(ROLE)" "$(CHAT)"

add-village: ## Add a village (and its district) to data/ with candidate river cells and a checklist (NAME= NAME_HI= DISTRICT= LAT= LON=; DISTRICT_HI= LGD_DISTRICT= LGD_VILLAGE= ID= OFFLINE=1)
	@test -n "$(NAME)" -a -n "$(NAME_HI)" -a -n "$(DISTRICT)" -a -n "$(LAT)" -a -n "$(LON)" || { echo 'usage: make add-village NAME=Bali NAME_HI="बाली" DISTRICT=Mandi LAT=31.6 LON=77.1 [DISTRICT_HI=मंडी LGD_DISTRICT=22 LGD_VILLAGE=... ID=bali OFFLINE=1]'; exit 2; }
	$(PYTHON) scripts/add_village.py --name "$(NAME)" --name-hi "$(NAME_HI)" --district "$(DISTRICT)" --lat "$(LAT)" --lon "$(LON)" \
	  $(if $(DISTRICT_HI),--district-hi "$(DISTRICT_HI)") $(if $(LGD_DISTRICT),--lgd-district "$(LGD_DISTRICT)") \
	  $(if $(LGD_VILLAGE),--lgd-village "$(LGD_VILLAGE)") $(if $(ID),--id "$(ID)") $(if $(OFFLINE),--offline)

staff-assign: ## Assign a staff account to districts, for the district scope (STAFF= DISTRICTS="Mandi,Kullu"; empty DISTRICTS removes)
	@test -n "$(STAFF)" || { echo 'usage: make staff-assign STAFF=officer3 DISTRICTS="Mandi,Hamirpur"'; exit 2; }
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.staff "$(STAFF)" "$(DISTRICTS)"

recipient-role: ## Make a registered person a relay or a villager again (VILLAGE= ID=<chat id or v_...> ROLE=pradhan|gauge_reader|task_force|villager)
	@test -n "$(VILLAGE)" -a -n "$(ID)" -a -n "$(ROLE)" || { echo 'usage: make recipient-role VILLAGE=gohar ID=123456789 ROLE=pradhan'; exit 2; }
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.voice role "$(VILLAGE)" "$(ID)" "$(ROLE)"

voice-list: ## List a village's voice numbers, masked (VILLAGE=gohar)
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.voice list $(or $(VILLAGE),gohar)

voice-remove: ## Stop calls to one recipient (VILLAGE= ID=v_...)
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.voice remove "$(VILLAGE)" "$(ID)"

voice-urls: ## Print the three URLs for the Exotel flow (contain the webhook key: treat as secret)
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.voice urls "$$STACK_ApiUrl"

officer-phone: ## The duty officer's phone for the wake-up call (OFFICER=officer1 PHONE=+91..|remove|show)
	@test -n "$(OFFICER)" -a -n "$(PHONE)" || { echo 'usage: make officer-phone OFFICER=officer1 PHONE=+919812345678'; exit 2; }
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.voice officer "$(OFFICER)" "$(PHONE)"

gauge-sim: ## Send a SIMULATED rising river gauge to the deployed stack (VILLAGE=gohar, FAST=1 for five readings at once)
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.gauge_sim $(or $(VILLAGE),gohar) $(if $(FAST),--fast,)

gauge-provision: ## Create the AWS IoT thing + certificate for a village gauge, key in SSM (VILLAGE=gohar, DELETE=1 to remove)
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.iot_provision $(or $(VILLAGE),gohar) $(if $(DELETE),--delete,)

gauge-sim-mqtt: ## Publish a SIMULATED rising river over MQTT (AWS IoT Core, X.509) (VILLAGE=gohar, SLOW=1 for real time, RAIN=120 for a mm/h burst)
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.gauge_sim_mqtt $(or $(VILLAGE),gohar) $(if $(SLOW),--slow,) $(if $(RAIN),--rain $(RAIN),)

device-provision: ## Create the AWS IoT thing + certificate for a siren, box or relay (KIND=siren VILLAGE=thunag, DEVICE=, DELETE=1)
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.iot_provision $(or $(VILLAGE),thunag) --kind $(or $(KIND),siren) $(if $(DEVICE),--device $(DEVICE),) $(if $(DELETE),--delete,)

siren-sim: ## Run a SIMULATED siren node on AWS IoT Core: verifies signed commands, reports "verified" (VILLAGE=thunag, FAULT=mic_dead)
	$(STACK_ENV); cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.siren_sim_mqtt $(or $(VILLAGE),thunag) $(if $(FAULT),--fault $(FAULT),)

protocol-vectors: ## Regenerate the device protocol's golden vectors (firmware/test/vectors/protocol_vectors.json; TEST ONLY keys)
	cd backend && PYTHONPATH=src $(PYTHON) -m Pukaar.scripts.protocol_vectors

ses-verify: ## Ask SES to verify an address for after-action e-mail (EMAIL=you@example.com); the owner clicks the link
	@test -n "$(EMAIL)" || { echo "usage: make ses-verify EMAIL=you@example.com"; exit 2; }
	aws sesv2 create-email-identity --region $(or $(AWS_REGION),us-east-1) --email-identity "$(EMAIL)"
	@echo "SES sent a verification e-mail to $(EMAIL). Its owner must click the link in it (valid 24 hours)"
	@echo "before SES will send from or, in the sandbox, to this address. Check: aws sesv2 get-email-identity --email-identity $(EMAIL)"

smoke: ## Read-only check of the live site and API: pages, axe, sideways scroll, API shapes, 401s (SMOKE_SITE=, SMOKE_API=)
	node scripts/smoke.mjs

it: ## Run real approval executions against the deployed stack
	$(PYTHON) scripts/it_workflow.py

local: ## Run backend (PUKAAR_MODE=local, :8000) and Vite dev server (:5173)
	trap 'kill 0' EXIT; \
	(cd backend && PUKAAR_MODE=local PYTHONPATH=src $(PYTHON) -m uvicorn Pukaar.main:app --reload --host 127.0.0.1 --port 8000) & \
	(cd frontend && VITE_API_BASE=http://127.0.0.1:8000 npm run dev) & \
	wait
