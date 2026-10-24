# Evening end-to-end checklist

What is ready, what needs your hands, in the order to do it. Everything up to step 6 is read-only.

## 0. Pull and check

```bash
cd ~/code/znacht && git pull && make check && make test-ha
```

## 1. Secrets (never in the repo)

Create `~/.config/znacht/env` (mode 600) from `deploy/.env.example`. Needed tonight:

- `ANTHROPIC_API_KEY`: the planner has only been exercised against a fake client so far.
- `ZNACHT_COOKIDOO_EMAIL` / `ZNACHT_COOKIDOO_PASSWORD` (first run only; the token file replaces the password afterwards).
- Migros: copy `~/.config/migros-mcp/session.json` to `~/.config/znacht/migros-session.json`. No password needed.
- `ZNACHT_API_TOKEN`: any long random string.

## 2. Household file

`cp examples/household.example.yaml ~/.config/znacht/household.yaml` and edit: members, rules, pantry, postcode, and the two Migros **list IDs** under `store_lists` (`znacht` prints them: see step 4). The seed rules file from the Health project goes to `docs/seed/meal-planning-rules.md` when you have it; the YAML stands in until then.

## 3. Dry runs, read-only

```bash
set -a; . ~/.config/znacht/env; set +a
uv run znacht cookidoo-dry-run --week 2026-10-26            # My Week + a search
uv run python scripts/record_migros.py --session ~/.config/znacht/migros-session.json   # re-records the cassette too
```

## 4. List IDs

```bash
uv run python -c "
import asyncio; from znacht_migros import *
async def m():
    async with MigrosSession(MigrosSettings.from_env()) as s:
        for r in await MigrosGroceryStore(s).lists(): print(r.id, r.kind, r.name)
asyncio.run(m())"
```

Put the online basket's ID under `store_lists.online` and the in-person list's ID under `store_lists.in_store`. If you only have one list, create a second one in the Migros app first.

## 5. Plan with the real planner, on the real catalogues, still writing nothing

```bash
ZNACHT_RECIPE_SOURCE=cookidoo ZNACHT_SINK=cookidoo ZNACHT_STORE=migros ZNACHT_PLANNER=anthropic \
ZNACHT_HOUSEHOLD=~/.config/znacht/household.yaml ZNACHT_DATA_DIR=~/.local/share/znacht uv run znacht-engine
```

In a second terminal: `curl -X POST -H "Authorization: Bearer $ZNACHT_API_TOKEN" -d '{"week":"2026-10-26"}' -H 'Content-Type: application/json' localhost:8787/api/plan_week`, then open `http://localhost:8787/brief?token=$ZNACHT_API_TOKEN`. Read the Brief. Nothing has been written anywhere yet.

Things to look at on the first real Brief: the Cookidoo tag inference (fish, red meat, legumes) on the chosen recipes, quantities that came from free-text notations (`raw` is shown in the API), and which items Migros marked non-deliverable once they are on the list (that only appears after an apply; see 7).

## 6. The first write: Approve

Press **Approve** on the Brief (or `POST /api/apply`). This writes My Week on Cookidoo and both Migros lists. It is the first time the write paths run against the real services. Check in the Cookidoo app and the Migros app. If the free-text item type is wrong, the Migros list update fails loudly and nothing else is lost; tell me the error text and I will fix the type.

## 7. Second run

Run `plan_week` again. Migros has now told us per item what it could not deliver to your address; the second Brief should move those to the store run automatically (the learned availability is persisted in the engine's SQLite).

## 8. Home Assistant

HACS → custom repository `https://github.com/sbarkar/znacht` (integration) → install Znacht → add integration with the engine URL and token. You get `todo.znacht_online_basket`, `todo.znacht_store_run`, `calendar.znacht_meal_plan`, the sensors, and the services. For notifications set `ZNACHT_HA_URL`, `ZNACHT_HA_TOKEN` (long-lived token) and `ZNACHT_HA_NOTIFY=mobile_app_<your phone>` on the engine.

## 9. Deploy on teodor

The Proxmox API token the MCP uses may not create containers (403 on `VM.PowerMgmt` today). From the host, as root:

```bash
curl -fsSL https://raw.githubusercontent.com/sbarkar/znacht/main/deploy/lxc/create.sh | VMID=102 bash
```

Then inside the LXC: edit `/opt/znacht/deploy/.env`, `docker compose up -d --build`, copy `household.yaml` and `migros-session.json` into the `znacht-data` volume, and add the Caddy snippet with the LXC's IP. Point the HA integration at the Caddy hostname.

## Known gaps to capture tonight

- **Delivery slot endpoint**: open migros.ch checkout with the browser's network tab open, pick a slot, and copy the request path and response shape into an issue. Until then slots come from `delivery.slot_templates` in the household YAML.
- **Free-text list item type** on Migros (currently `FREE_TEXT`, unverified).


## Outcome of the first live evening (2026-10-24)

- Steps 0–7 done. Run 8 ("Cosy Autumn Comforts", Claude planner + matcher) was approved and applied: My Week for 26 Oct–1 Nov holds the seven dinners (the eight entries that were there before are recorded in run 8's `plan_diff.remove` in the engine database and can be re-added), the Migros "Shopping list" (340420) holds 32 product lines, "In-Person Shopping" (97185194) holds 12.
- **Free text on Migros lists does not work through the items API**: `PUT /shopping-list/public/v3/items` answers `400 items.invalid_id` for type `FREE_TEXT`. Products and free text are now sent separately so the products always land; free-text lines are listed on the Brief for you to add in the app. Capturing the app's free-text request is the next reverse-engineering item.
- Migros answered per item after the write: `AVAILABLE`, `UNAVAILABLE`, `UNAVAILABLE_FOR_WAREHOUSE`. Run 9 (not applied) used that to move baby spinach and parsley to the store run.
- Still to capture: the delivery-slot endpoint.
- Not yet tested: the Home Assistant integration (the engine ran on the workstation at 192.168.1.148, HA lives on 192.168.4.x) and the LXC deployment.
