.PHONY: up down test race-test expiration-test lint typecheck clean

up:
	docker compose up -d --build

down:
	docker compose down

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
