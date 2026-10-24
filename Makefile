.PHONY: sync lint typecheck test check e2e-dry-run demo

sync:
	uv sync --all-packages

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

test:
	uv run pytest

check: lint typecheck test

demo:
	uv run znacht demo --household examples/household.example.yaml --week 2026-10-26

# Live accounts, read-only. Needs ZNACHT_COOKIDOO_EMAIL (+ PASSWORD on first run) in the env.
e2e-dry-run:
	uv run znacht cookidoo-dry-run --week $(shell date -d 'next monday' +%F)

record-cookidoo:
	uv run python scripts/record_cookidoo.py --env-file $(ENV_FILE)

record-migros:
	uv run python scripts/record_migros.py
