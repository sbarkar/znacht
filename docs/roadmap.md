# Znacht roadmap

Status as of 2026-10-24, late evening. This is the hand-off document: any session can pick the top
unblocked item of the highest tier, do it, and update this file. Phases 1–7 in `architecture.md` are done;
what follows is what makes Znacht something the household actually lives with.

## Where we are

- The engine runs in Proxmox LXC 102 (`znacht`, 192.168.4.80, reserved in UniFi) as a systemd service
  (`deploy/lxc/`). Home Assistant (192.168.4.81, plain HTTP) is connected and shows the app in its sidebar.
- Live adapters: Cookidoo (recipes, My Week), Migros (products, two lists, learned availability), Claude
  (planner and product matcher). Twelve runs in the database; run 12 (week of 2 Nov) awaits approval.
- Proven end to end: plan, Brief, apply to My Week and both lists, revert, swaps and locks in the app.
- Standing rules: no checkout or payment, ever (tested); nothing is written to a live account without an
  approved view that shows My Week removals; recorded fixtures are read-only (ADR-0007); secrets live in
  `/etc/znacht/env` on the LXC and `~/.config/znacht/env` on the workstation, never in the repo or in chat.

## How to work an item

1. Say which item you take and write a one-line note under it ("in progress, session X, date").
2. Non-obvious decisions get an ADR in `docs/decisions/` (next number: 0012).
3. Before any commit: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q`
   and `make test-ha` when `custom_components/` changed.
4. Deploy is Sergej's command (needs his ssh to the Proxmox host):
   `ssh -t root@192.168.4.10 'pct exec 102 -- /opt/znacht/deploy/lxc/install.sh'`
   then a HACS redownload and HA restart if the integration changed.
5. Writes to Cookidoo or Migros only on Sergej's explicit go, after he has seen the view.
6. When done: tick it here, move anything learned into the relevant ADR or README.

## Decisions Sergej still owns

- Timeline horizon for the Week screen (default proposed: today + 13 days).
- Whether voice may *apply* a plan or only propose, swap and read (proposal: never apply by voice).
- Voice languages: Swiss German sentences are not something Assist handles; proposal is English plus a
  small set of German sentences.
- Public hostname for the Caddy front (needed for P2-6).

---

## P0 · A week you can trust

### 1. The Week screen becomes a timeline  ✅ done 2026-10-24 (ADR-0011)

**Done 2026-10-24.** `GET /api/timeline`, the Timeline screen, `sensor.znacht_unplanned_days`, manual
dinners in the calendar, `locked_dates` on `plan_week` with the planner told about locks. Coverage is
the first heuristic from ADR-0011; item 3 upgrades "arriving" to a fact.

**Problem.** The Week screen shows the *latest run's* week. It cannot answer the three questions that
matter at the fridge: what is actually planned for the coming days, which days have nothing yet, and do
we have the food for them. Dinners that live in Cookidoo My Week but came from a hand-made week are
invisible, and "groceries" is a per-run basket, not a per-day answer.

**Design.**

- A rolling timeline from today for N days (default 14), grouped by ISO week, replacing the run-centred
  list. Each day has one of four states, each with its own look:
  - **planned**: a dinner is in My Week (source shown: "Znacht run 12" or "yours"), tap to swap/lock;
  - **proposed**: a run that still needs approval has a dinner here (shown dimmed with an "Approve" pill);
  - **empty**: nothing anywhere, with a single "Plan the gaps" call to action per week;
  - **past**: cooked or skipped, collapsed.
- A groceries badge per day: `arriving <weekday> <slot>` (an order exists and covers it), `in online list`
  (listed, not ordered), `store run` (on the in-store list), `nothing` (no coverage). A week header sums it
  up: "5 of 7 planned · online order Mon 19:00 covers Mon–Thu · store run pending · Fri–Sun no groceries".
- "Plan the gaps" plans only the empty days, keeping everything already in My Week locked, and lands as a
  proposal like any other run. "Shop for these days" builds lists for the chosen days only.

**Engine.**

- `GET /api/timeline?from=YYYY-MM-DD&days=14` returning one record per day: date, state, dinner (title,
  recipe id, source run id or `manual`), groceries coverage, and per week the run id awaiting approval.
  Sources: `sink.read_week()` for every ISO week in range (My Week is the truth, cache a few minutes),
  runs by week from the repo, lists via `store.read_list()`, orders via item 3 below (until then coverage
  is "listed" vs "nothing").
- Coverage heuristic, first version: the dinners of an applied run are covered by that run's lists; a
  placed order covers the days from its delivery until the next delivery. Refine with needs explosion
  later.
- `plan_week` already accepts `locked_dates`; "Plan the gaps" is a run with every planned date locked and
  `fixed_plan` for them, which skips the LLM for those days.
- HA: a `sensor.znacht_unplanned_days` (count, with the dates as attributes) and the calendar carrying the
  `manual` entries too.

**Where.** `packages/znacht-engine/src/znacht_engine/service.py` (`timeline()`), `app.py` (route),
`static/app.js` (Week → Timeline component; keep the swap sheet), `static/app.css`, `tests/engine/`,
`custom_components/znacht/sensor.py`, ADR-0011 for "My Week is the truth, runs are proposals".

**Done when** Sergej opens the app and can say within five seconds what is for dinner for the next seven
days, which days are blank, and whether the food for each day is ordered, listed or missing.

**Size** L: engine half a day, app one day, HA sensor an hour. **Depends on** nothing; item 3 upgrades it.

### 2. Plan the gaps, not the week  ← start here

Make partial planning a first-class verb: any date range, existing My Week dinners locked by default,
recent weeks fed to the planner as today. Mostly exists (`locked_dates`, `fixed_plan`); needs a clean API
(`POST /api/plan` with `from`, `to`, `lock_existing=true`), the "Plan the gaps" button in item 1, and the
HA service `znacht.plan_week` growing `from`/`to`. **Size** M. **Depends on** 1 for the UI.

### 3. Real grocery truth from Migros orders

Read placed orders and their delivery slots so "ordered" and "arriving Monday 19:00" are facts rather than
list membership. Add an optional `orders()` to the `GroceryStore` port (ADR-0008 style: optional, probed
with `hasattr`), implement it in `znacht-migros`, record a scrubbed read-only cassette. This is also where
the still-missing delivery-slot endpoint gets captured: Sergej opens migros.ch checkout with the network
tab open, picks a slot, and pastes request path and response shape (no cookies) into an issue. The
household `slot_templates` stay as fallback. **Size** M, needs Sergej for the capture. **Depends on** nothing.

## P1 · Talk to it

### 4. Voice control through Home Assistant Assist

Two layers, in this order:

- **Sentences and intents in the integration.** `custom_components/znacht/intents.py` plus
  `custom_sentences/en/` and `de/`: "what's for dinner tonight / tomorrow / on Wednesday", "what's left to
  plan this week", "swap Wednesday", "plan the gaps", "put milk on the store run", "how much is the
  basket", "when does the delivery come". Handlers call the engine and answer in one short sentence.
  Swaps and planning create proposals; nothing is applied by voice (decision above; ADR-0012).
- **The engine as an MCP server.** `GET/POST /mcp` on the engine (FastMCP or hand-rolled over the
  existing service methods: timeline, alternatives, swap, lock, plan, lists, add item, approve-gate
  disabled). Then HA's LLM conversation agent, the Claude app and any other assistant can use Znacht as
  tools, with the same bearer token. HA already has an MCP client integration.

**Done when** the Voice PE in the kitchen answers "what's for dinner tonight" and "add milk to the store
run" and the item shows in the app. **Size** M + M. **Depends on** 1 for the "what's left to plan" answers.

### 5. Notifications from the engine

Set `ZNACHT_HA_URL`, `ZNACHT_HA_TOKEN` (long-lived token from Sergej) and `ZNACHT_HA_NOTIFY` in
`/etc/znacht/env`; the code exists (`ha.py`). Events: proposal ready (with Brief link), approval applied,
delivery tomorrow, "three empty days ahead" (from item 1). Actionable buttons: Approve, Open. **Size** S.

## P2 · Reach

### 6. HTTPS in front of the LXC

Caddy LXC 109 (192.168.4.2) gets `deploy/caddy/Caddyfile.snippet` with the znacht address and a hostname
Sergej chooses; `ZNACHT_PUBLIC_URL` and the HA integration move to the HTTPS URL. Needed for phone links
off the LAN and for a Nabu Casa HA, whose sidebar iframe refuses plain HTTP. **Size** S.

### 7. Migros free text that sticks

`PUT /shopping-list/public/v3/items` rejects `FREE_TEXT` with `items.invalid_id`; the app lists free text
for manual entry. Capture the request the Migros app sends for a free-text line and implement it. Until
then, free text goes to the HA todo list only. **Size** S after capture.

### 8. Household and Connections, second pass

Edit `default_servings`, delivery `slot_templates` and store lists in the app; upload a lab PDF in the
Health card (`znacht extract lab` exists as CLI); the savings card on Connections reads the real ledger
and explains it. **Size** M.

### 9. Second sources as proof the ports hold

A `RecipeSource` for Mealie or Tandoor (both have APIs) and a second `GroceryStore` (Coop) with the same
contract suites; a basket comparison across stores in Groceries. Community-shaped work: write the
adapter guide first (`docs/adapters.md`: ports, contract suites, cassette rules). **Size** L each.

## P3 · Packaging and hygiene

### 10. Releases

**Done 2026-10-25** except the add-on build: `release.yml` publishes `ghcr.io/sbarkar/znacht` on every
push to `main` and, for a `v*` tag whose version matches `manifest.json` and the add-on's `config.yaml`,
creates the GitHub release HACS offers (`CONTRIBUTING.md`, "Cutting a release"). Left: the add-on build
in CI (`addon/`), and cutting the first release. **Size** S.

### 11. Operations

Journal access for sessions: the Proxmox MCP exec allowlist only permits `hostname -I` and
`systemctl is-active`; adding `journalctl -u znacht -n 200` and `systemctl status` lets a session read
engine logs without Sergej. A monthly `uv lock --upgrade` check in CI. A note in `deploy/lxc/README.md`
on restoring from a Proxmox backup. **Size** S, mostly outside the repo.

### 12. Planner quality

Prompt and matcher evaluation set from the recorded runs (which products were right, which swaps Sergej
rejected); seasonal search terms for Migros; toddler-portion logic in needs explosion. **Size** M, ongoing.

---

## Done (for the record)

- 2026-10-24: phases 1–7; live end-to-end; the app; LXC deployment and cut-over; HA reconfigure step;
  UniFi reservation. Details in `docs/evening-checklist.md` and the ADRs.
- 2026-10-24, late: P0-1, the Week screen as a timeline (ADR-0011).
