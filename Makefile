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

# Home Assistant tests use HA's own pins, which do not mix with the engine's: they get their own venv.
# HA 2025.1 is the last line with wheels for Python 3.12 everywhere; newer HA needs 3.13 plus a C toolchain.
.venv-ha:
	uv venv --python 3.12 .venv-ha
	uv pip install --python .venv-ha "pytest-homeassistant-custom-component<0.13.210" "pycares<4.6"

test-ha: .venv-ha
	.venv-ha/bin/python -m pytest tests_ha -q -p no:cacheprovider

demo:
	uv run znacht demo --household examples/household.example.yaml --week 2026-10-26

# Live accounts, read-only. Needs ZNACHT_COOKIDOO_EMAIL (+ PASSWORD on first run) in the env.
e2e-dry-run:
	uv run znacht cookidoo-dry-run --week $(shell date -d 'next monday' +%F)

record-cookidoo:
	uv run python scripts/record_cookidoo.py --env-file $(ENV_FILE)

record-migros:
	uv run python scripts/record_migros.py
