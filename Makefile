# Rețeaua Vie: one entry point for setup, data, dev servers, tests and the stack.
# Paths outside the repo come only from DATA_DIR and ENV_FILE (override on the command line).

SHELL := /bin/bash
DATA_DIR ?= /srv/unihack/app/data
ENV_FILE ?= /srv/unihack/app/.env
# human review sheets of the eval labels (private, outside the repo): `make eval-review` writes them
EVAL_REVIEW_DIR ?= /srv/unihack/app/docs/eval-review
API_PORT ?= 3000
WEB_PORT ?= 3010
export DATA_DIR ENV_FILE EVAL_REVIEW_DIR

ROOT := $(CURDIR)
BACKEND := $(ROOT)/backend
FRONTEND := $(ROOT)/frontend
FRONTEND_V3 := $(ROOT)/frontend-v3
COMPOSE := docker compose -f $(ROOT)/infra/compose.yml
FNM := eval "$$(fnm env 2>/dev/null)"

.PHONY: help setup data data-city record precompute dev dev-stop test eval eval-review web demo up down

help:
	@echo "make setup | data | data-city | record | precompute | dev | dev-stop | test | eval | eval-review | web | demo | up | down"
	@echo "DATA_DIR=$(DATA_DIR)  ENV_FILE=$(ENV_FILE)"

setup:
	cd $(BACKEND) && uv sync
	@if [ -f $(FRONTEND)/package.json ]; then $(FNM); cd $(FRONTEND) && pnpm install; fi
	@java -version 2>&1 | grep -q 'version "21' && echo "Java 21: ok" \
		|| echo "WARN: Java 21 missing (sudo apt install openjdk-21-jre-headless)"
	@cd $(BACKEND) && uv run python -c "import weasyprint" 2>/dev/null && echo "WeasyPrint: ok" \
		|| echo "WARN: WeasyPrint system libs missing (sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0)"

data:
	bash $(BACKEND)/scripts/data/fetch_all.sh

# City sources only (SMTT GTFS, city API copies, STPT notices, sesizări), no osmium / Java; `make data` runs it too.
PYRUN := uv run --no-project --quiet --python 3.12 python -I
RECORD_ENV = DATA_DIR=$(DATA_DIR) LIVE_DIR=$${LIVE_DIR:-$(DATA_DIR)/live}
data-city:
	cd $(BACKEND) && $(PYRUN) scripts/data/fetch_city.py

# Live recording in tmux rv-record: vehicles every 15 s; GTFS, STPT notices and sesizări every hour.
record:
	@if tmux has-session -t rv-record 2>/dev/null; then echo "rv-record already running"; else \
		tmux new-session -d -s rv-record -n vehicles -c $(BACKEND) \
			"$(RECORD_ENV) $(PYRUN) scripts/data/record_vehicles.py" \; set-option -t rv-record remain-on-exit on >/dev/null && \
		tmux new-window -d -t rv-record -n city -c $(BACKEND) \
			"$(RECORD_ENV) $(PYRUN) scripts/data/fetch_city.py --every 3600 --only gtfs,stpt,sesizari" && \
		echo "recording: tmux attach -t rv-record (windows vehicles, city); stop: tmux kill-session -t rv-record"; fi

precompute:
	cd $(BACKEND) && uv run python -m app.precompute

# Dev servers in tmux: backend on :$(API_PORT); frontend on :$(WEB_PORT) once frontend/ exists.
dev:
	@tmux has-session -t rv-api 2>/dev/null && echo "rv-api already running" || \
		tmux new-session -d -s rv-api -c $(BACKEND) \
		"ENV_FILE=$(ENV_FILE) DATA_DIR=$(DATA_DIR) uv run uvicorn app.main:app --host 127.0.0.1 --port $(API_PORT) --reload"
	@if [ -f $(FRONTEND)/package.json ]; then \
		tmux has-session -t rv-web 2>/dev/null && echo "rv-web already running" || \
		tmux new-session -d -s rv-web -c $(FRONTEND) \
		'$(FNM); pnpm dev --host 127.0.0.1 --port $(WEB_PORT)'; \
	else echo "no frontend/package.json yet: backend only"; fi
	@echo "API: http://127.0.0.1:$(API_PORT)/api/health   (tmux attach -t rv-api)"

dev-stop:
	-tmux kill-session -t rv-web 2>/dev/null
	-tmux kill-session -t rv-api 2>/dev/null

test:
	cd $(BACKEND) && uv run pytest -q
	@if [ -f $(FRONTEND)/package.json ]; then $(FNM); cd $(FRONTEND) && pnpm test --if-present; fi

eval:
	cd $(ROOT) && uv run --project $(BACKEND) python eval/run.py

# (re)write the review sheets; ticks already made are kept (eval/review.py)
eval-review:
	cd $(ROOT) && uv run --project $(BACKEND) python eval/review.py write

# Build the frontend to frontend/dist (served at / by the backend and baked into the image).
web:
	@if [ -f $(FRONTEND)/package.json ]; then $(FNM); cd $(FRONTEND) && pnpm install --frozen-lockfile && pnpm build; \
	else echo "no frontend/package.json yet: nothing to build"; fi
	@# frontend-v3 is the public frontend (/, /app/* and the QR page /a/*); v1 ships next to it as v1.html (/step/*)
	@if [ -f $(FRONTEND_V3)/package.json ] && [ -f $(FRONTEND)/dist/index.html ]; then $(FNM); cd $(FRONTEND_V3) \
		&& pnpm install --frozen-lockfile && pnpm build \
		&& cp $(FRONTEND)/dist/index.html dist/v1.html && cp -r $(FRONTEND)/dist/assets/. dist/assets/; fi

# One process on :$(API_PORT) for / (frontend/dist) and /api, no reload (SPEC §3.4).
demo: web
	@if tmux has-session -t rv-api 2>/dev/null; then \
		echo "rv-api (make dev) already holds :$(API_PORT); it serves frontend/dist after a restart: make dev-stop demo"; \
	elif tmux has-session -t rv-demo 2>/dev/null; then echo "rv-demo already running"; \
	else tmux new-session -d -s rv-demo -c $(BACKEND) \
		"ENV_FILE=$(ENV_FILE) DATA_DIR=$(DATA_DIR) uv run uvicorn app.main:app --host 127.0.0.1 --port $(API_PORT)"; \
		echo "demo: http://127.0.0.1:$(API_PORT)/  (tmux attach -t rv-demo; stop: tmux kill-session -t rv-demo)"; fi

# Docker stack (SPEC §12): api on 0.0.0.0:3000 + worker (pre-compute, then exits).
# The containers run as you, so state/ and cache/ stay writable for make dev.
HOST_UID := $(shell id -u)
HOST_GID := $(shell id -g)
STACK_ENV := HOST_UID=$(HOST_UID) HOST_GID=$(HOST_GID) GIT_SHA=$(shell git rev-parse HEAD 2>/dev/null)

up: web
	@if [ -z "$$RV_PORT" ] && { tmux has-session -t rv-api 2>/dev/null || tmux has-session -t rv-demo 2>/dev/null; }; then \
		echo "a native server (rv-api / rv-demo) holds :3000: stop it first (make dev-stop; tmux kill-session -t rv-demo)"; exit 1; fi
	$(STACK_ENV) $(COMPOSE) up -d --build
	@echo "stack: http://127.0.0.1:$${RV_PORT:-3000}/api/health   logs: $(COMPOSE) logs -f api"

down:
	$(STACK_ENV) $(COMPOSE) down
