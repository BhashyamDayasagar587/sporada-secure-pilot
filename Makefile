# ALPR edge stack — operator shortcuts.
#
# Usage examples:
#   make preflight        # check host has Axelera + iGPU before we start
#   make up               # bring up the whole stack
#   make logs SERVICE=worker
#   make tail-events      # stream traffic:analytics
#   make tail-system      # stream traffic:system
#   make smoke            # import + compose-config sanity check
#   make down             # stop + remove containers
#   make clean            # also remove volumes (DANGER: wipes config_data)

COMPOSE      ?= docker compose -f deploy/docker-compose.intel-axelera.yml
SERVICE      ?= worker

.PHONY: help preflight up down logs tail-events tail-system smoke restart-worker shell clean

help:
	@awk 'BEGIN{FS=":.*?## "} /^[a-zA-Z_-]+:.*?## /{printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

preflight: ## Verify host has Axelera NPU + Intel iGPU before bringing the stack up
	@bash scripts/preflight.sh

up: preflight ## Bring up the full Phase 1 stack
	$(COMPOSE) up --build -d

down: ## Stop + remove containers (keeps volumes)
	$(COMPOSE) down

restart-worker: ## Restart just the worker (useful when swapping a .axl)
	$(COMPOSE) restart worker

logs: ## Tail logs for SERVICE=<name> (default: worker)
	$(COMPOSE) logs -f --tail=200 $(SERVICE)

tail-events: ## Tail the traffic:analytics Redis stream
	$(COMPOSE) exec worker python consume_analytics.py --block-ms 1000

tail-system: ## Tail the traffic:system Redis stream
	$(COMPOSE) exec redis redis-cli XREAD COUNT 50 BLOCK 0 STREAMS traffic:system $$

smoke: ## Offline import + docker compose config sanity check
	@bash scripts/smoke.sh

shell: ## Open a shell inside SERVICE=<name>
	$(COMPOSE) exec $(SERVICE) bash

clean: down ## Also remove volumes (DELETES config_data)
	$(COMPOSE) down --volumes

sync-root: ## Re-mirror edge/ contents to the alpr/ top level (keeps the two copies aligned)
	@cd .. && \
	for d in services ui deploy docs models config tools datasets; do \
	  rm -rf "$$d" && cp -r "edge/$$d" .; \
	done && \
	cp edge/README.md . && cp edge/.gitignore . && \
	echo "alpr/ root re-mirrored from edge/"
