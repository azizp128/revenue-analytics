.PHONY: help setup data db schema load metabase restore app reset down clean

# --- config: rename here if your compose service names differ ---------------
DB_SVC   := postgres_dataforge
MB_SVC   := postgres_metabase
APP_SVC  := metabase
DB_USER  := dataforge
DB_NAME  := dataforge
MB_USER  := metabase
MB_NAME  := metabase
DASH_URL := http://localhost:3001/dashboard/2-dataforge-revenue-dashboard
BACKUP   := $(shell ls -t backup/*.dump 2>/dev/null | head -1)
CSVS     := dim_client dim_domain dim_product fact_daily_usage

help: ## Show available commands
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

setup: data db schema load metabase restore app ## Run everything, then open the dashboard
	@echo "\nDone -> $(DASH_URL)"

data: ## Install deps and generate the synthetic dataset
	pip install -q numpy pandas
	python generate_data.py

db: ## Start the DataForge Postgres and wait until it accepts connections
	docker compose up -d $(DB_SVC)
	@until docker exec $(DB_SVC) pg_isready -U $(DB_USER) -d $(DB_NAME) -q; do sleep 1; done

schema: ## Create tables, indexes, and the v_revenue view
	docker exec -i $(DB_SVC) psql -U $(DB_USER) -d $(DB_NAME) < sql/01_schema.sql

load: ## Copy CSVs into the container and load them
	@$(foreach f,$(CSVS),docker cp data/$(f).csv $(DB_SVC):/tmp/$(f).csv;)
	docker exec -i $(DB_SVC) psql -U $(DB_USER) -d $(DB_NAME) < sql/02_load.sql

metabase: ## Recreate the Metabase app database (app must be stopped first)
	docker compose stop $(APP_SVC) 2>/dev/null || true
	docker compose up -d $(MB_SVC)
	@until docker exec $(MB_SVC) pg_isready -U $(MB_USER) -q; do sleep 1; done
	docker exec $(MB_SVC) psql -U $(MB_USER) -d postgres -c "DROP DATABASE IF EXISTS $(MB_NAME);"
	docker exec $(MB_SVC) psql -U $(MB_USER) -d postgres -c "CREATE DATABASE $(MB_NAME);"

restore: ## Restore the saved dashboard from the newest backup dump
	@test -n "$(BACKUP)" || { echo "No .dump found in backup/"; exit 1; }
	@echo "Restoring $(BACKUP)"
	docker cp $(BACKUP) $(MB_SVC):/tmp/backup.dump
	docker exec $(MB_SVC) pg_restore -U $(MB_USER) -d $(MB_NAME) --clean --if-exists /tmp/backup.dump

app: ## Start Metabase and wait until the dashboard responds
	docker compose up -d $(APP_SVC)
	@echo "Waiting for Metabase to boot (first start takes ~60s)..."
	@until curl -sf http://localhost:3001/api/health >/dev/null; do sleep 3; done

reset: ## Wipe and reload the DataForge data only (keeps Metabase intact)
	$(MAKE) schema load

down: ## Stop all containers
	docker compose down

clean: ## Stop containers and delete volumes and generated CSVs
	docker compose down -v
	rm -rf data/