# ADR-0009: The engine owns state; Home Assistant is a thin view; the Brief is the product

Status: accepted · 2026-10-24

## Context
Phase 5 needed a place for state (runs, learned availability, preferred products, pantry edits, price history, a savings ledger), a way to show a plan that a household can actually read and approve on a phone, and a Home Assistant integration that stays light.

## Decisions
1. **The engine (FastAPI + SQLite) is the single owner of state.** HA holds only a URL and a token. Every HA entity is a projection of `GET /api/status`, `/api/lists` and `/api/calendar`; every HA service is a `POST` to the engine. `pytest-homeassistant-custom-component` tests run against a mocked engine, in their own Python 3.13 environment (HA's pins do not coexist with the engine's).
2. **The Znacht Brief is the approval surface.** One server-rendered page per run: the week's theme and the chef's note from the planner, a card per dinner with minutes and cost per person, the money (basket, minimum, store run, savings this week and since the start), every swap and flag with its reason and CHF delta, the online basket, the store run grouped in the order you walk a Swiss supermarket, free-text items, and a single "Approve" button. Actionable HA notifications carry Approve and Review; Review opens the Brief. The Brief never contains a checkout button; after apply it links to the store's own basket page.
3. **Two-way todo sync is explicit.** Ticking an item in HA marks it done in the engine; adding an item in HA adds a free-text line to the current run. Neither writes to the store until the next approved apply. An explicit tick is the household's own action, so no extra approval is asked for it.
4. **Prices are remembered.** Every run records the online and in-store price seen per product, so later versions can flag price jumps; the ledger records savings and basket totals per applied week.
5. `optimize_products` currently re-runs the whole pipeline. A plan-preserving optimise pass is a follow-up (ADR to come).

## Consequences
- The HA integration has no business logic and no secrets beyond the engine token.
- The engine is one process with one SQLite file; backups are the `/data` volume.
- The Brief is plain HTML and CSS, works on a phone, in dark mode, and needs no JavaScript.
