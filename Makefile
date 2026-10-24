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

# Phase 2+: live accounts, read-only, prints the diff it would apply.
e2e-dry-run:
	@echo "e2e-dry-run needs live adapters (Phase 2+)."; exit 1
