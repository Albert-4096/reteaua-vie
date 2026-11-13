# Rețeaua Vie: one entry point for setup, data, dev servers, tests and the stack.
# Paths outside the repo come only from DATA_DIR and ENV_FILE (override on the command line).

SHELL := /bin/bash
DATA_DIR ?= /srv/unihack/app/data
ENV_FILE ?= /srv/unihack/app/.env
API_PORT ?= 3000
WEB_PORT ?= 3010
export DATA_DIR ENV_FILE

ROOT := $(CURDIR)
BACKEND := $(ROOT)/backend
FRONTEND := $(ROOT)/frontend
COMPOSE := docker compose -f $(ROOT)/infra/compose.yml
FNM := eval "$$(fnm env 2>/dev/null)"

.PHONY: help setup data precompute dev dev-stop test eval up down

help:
	@echo "make setup | data | precompute | dev | dev-stop | test | eval | up | down"
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

up:
	@test -f $(ROOT)/infra/compose.yml || { echo "infra/compose.yml does not exist yet"; exit 1; }
	$(COMPOSE) up -d --build

down:
	@test -f $(ROOT)/infra/compose.yml || { echo "infra/compose.yml does not exist yet"; exit 1; }
	$(COMPOSE) down
