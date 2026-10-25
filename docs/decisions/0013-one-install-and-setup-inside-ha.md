# ADR-0013: One install from HACS; the first setup happens in Home Assistant's own forms and the app

Status: accepted · 2026-10-25 · builds on ADR-0012

## Context
After ADR-0012 a Home Assistant OS household installs two things (the add-on from the add-on store, the
integration from HACS), types its accounts into add-on options, and edits `household.yaml` in a file
editor for the Migros list IDs and the delivery slot. Each step is small; together they keep out the
households Znacht is for, who are not technical. ADR-0012 deferred running the engine inside Home
Assistant, for reasons that still hold.

## Decision
1. **HACS is the only install.** On Home Assistant OS the integration's setup offers "Run Znacht here
   (recommended)": it adds the add-on repository to the Supervisor if missing, installs and starts the
   add-on through Home Assistant's add-on manager (the way Z-Wave JS and Matter do), and connects to it.
   "I already run the engine elsewhere" keeps the URL and token form, and is the only path without a
   Supervisor.
2. **Accounts are asked in the integration's forms** (Cookidoo, Migros, Claude, each skippable to the
   sample adapters), stored as the add-on's options, and checked by the engine after a restart; a
   wrong password is shown on the form it belongs to. The integration's Configure button changes them
   later. The integration never stores the account passwords itself.
3. **The engine starts even when an account fails.** A failed login no longer stops the engine; the
   adapter is replaced by one that explains the failure on use, and `GET /api/connections` reports each
   connection. Planning then fails with that message instead of the add-on restarting in a loop.
4. **The first household is made in the app.** While the household is still the shipped example, the
   app opens a Welcome wizard: people, how you cook, delivery postcode and slot, and the two Migros lists
   picked from the account (`GET /api/store/lists`). `POST /api/setup` writes a fresh, validated
   household file; the example is kept as `household.example.yaml`. The Household screen edits the
   delivery slot and the lists afterwards. No file editor is needed for anything.

## Consequences
- A household goes from HACS to its first planned week with forms and taps only.
- The integration depends on the Supervisor API for the recommended path, so it declares `hassio` as an
  after-dependency and keeps working without it.
- Two engines can exist side by side (an LXC and the add-on); the integration supports one entry, and the
  docs say to remove the old entry before switching.
