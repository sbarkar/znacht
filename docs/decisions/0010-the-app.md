# ADR-0010: The Znacht app lives in the engine, opens from the HA sidebar, has no build step

Status: accepted · 2026-10-24

## Context
The Brief was a read-only page with one button. The household wants to work the week: swap a dinner, lock one, move an item between delivery and the store run, change a rule or the pantry, and see every connected store and appliance in one place, from a phone, through Home Assistant, without being technical.

## Decisions
1. **One app, served by the engine at `/app`.** Four screens: Week, Groceries, Household, Connections. Phone-first, two columns on a laptop. Dark, warm, big type, real buttons; no emoji.
2. **No build step.** Vendored `htm` + `preact` standalone module (Apache-2.0, 13 KB) under `static/vendor/`, plain ES modules, one CSS file. Contributors need Python only. If the app outgrows this, a bundler is a later ADR, not a prerequisite.
3. **Token handling.** The HA sidebar panel is an iframe on `/app?token=…`. The app stores the token in its own origin's local storage once and sends it as a bearer header; no cookies, so it works inside a cross-site iframe over plain HTTP on a LAN. The token still appears once in the panel URL inside HA's config; HTTPS through Caddy is recommended once the engine leaves the LAN.
4. **Swaps are new runs.** A swap, a move or "plan again" creates a new run derived from the base run: same candidate pool, same locks and channel overrides, no new LLM call for swaps and moves (the plan is fixed, only needs, split and optimisation rerun). Alternatives come from the stored pool and are pre-checked against the rules; only real dinners (four or more ingredients) are offered.
5. **Household edits write the YAML.** The YAML stays the human-readable source of truth. The app patches it through ruamel's round-trip loader so comments and order survive, validates the result through the normal loader before writing, and writes atomically.
6. **Pantry by photo is a draft.** The photo goes to the planner's extractor; the app shows the items with confidence and the household ticks what is right before anything is saved.

## Consequences
- The Brief page remains as the notification landing page and printable summary; the app is where work happens.
- The HA integration gains a sidebar entry but no new logic.
- Every write still goes through `apply` with the removals shown first, and every applied run can be reverted.
