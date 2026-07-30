.PHONY: up up-local down down-local test race-test expiration-test lint typecheck clean observability-up observability-down

up:
	docker compose up -d --build

up-local:
	docker compose -f docker-compose.local.yml up -d --build

down:
	docker compose down

down-local:
	docker compose -f docker-compose.local.yml down

observability-up:
	docker network create shide-observability || true
	docker compose -f ../shide-observability/docker-compose.yml up -d

observability-down:
	docker compose -f ../shide-observability/docker-compose.yml down

test:
	uv run pytest -v

race-test:
	uv run python scripts/race_test.py

expiration-test:
	uv run python scripts/expiration_test.py

lint:
	uv run ruff check .

typecheck:
	uv run mypy src

clean:
	docker compose down -v
