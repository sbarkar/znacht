# Phase 0 discovery — build or extend?

Date: 2026-10-24. Status: draft for review. Nothing here is committed or git-initialised.

## 1. Verdict

**Build a new project, and treat the existing recipe managers as adapter targets, not competitors.**

Nothing open source today covers the loop *plan → push to the appliance → split online/in-store → optimise products → hand over to a human*. The projects that come closest each cover one slice:

| Project | What it is | Why it is not the base |
|---|---|---|
| [Mealie](https://github.com/mealie-recipes/mealie) (13.7k stars, AGPL-3.0, Python) | Recipe manager with meal plan, shopping lists, official HA integration (calendars, todo lists, services) | It stores recipes; it does not plan under constraints, talk to stores, or push to appliances. Its plugin story is "use the REST API". Good future `RecipeSource` + `MealPlanSink` adapter. |
| [Tandoor](https://github.com/TandoorRecipes/recipes) (8.7k, AGPL) | Same category, more features, nutrition, supermarket aisle mapping | Same reasoning. Candidate adapter. |
| [KitchenOwl](https://github.com/TomBursch/kitchenowl) (3.8k, AGPL, Flask + Flutter) | Shared grocery list + recipes, separate HA integration | Grocery-list first, no planner, no store APIs. |
| [myMeal](https://github.com/Amantux/mymeal) (1 star, AGPL, created 2026-07, Flask + Vue) | "AI meal planning, pantry, smart shopping lists, HA add-on + HACS + MCP" | Closest in *pitch*. Solo project, Flask monolith, pluggable only at the LLM-provider layer, no store adapters, no appliance sink, no health rules, no pantry (delegated to a sister app). Extending it would mean rewriting its core. |
| [MealMCP](https://github.com/bobjansen/MealMCP) (2 stars, AGPL) | Meal planning + pantry with an MCP server | Flask app, no stores, no HA. |
| GitHub "LLM meal planner" repos (smart-grocery-agents, Meal-agents, MealAgent, food-service…) | Prototypes | All stop at a shopping list or a mocked cart. Several note that reaching a real retailer cart is the hard part. |
| [swissgroceries-mcp](https://github.com/nicktcode/swissgroceries-mcp) (37 stars, TypeScript, PolyForm Shield) | Cross-chain search for Migros, Coop, Aldi, Denner, Lidl, Farmy, Volg, Otto's | Read-only (search, promotions, stock, nutrition). No baskets, no lists, no auth. Licence forbids competing products from v0.10 on, so read it for endpoint knowledge, never vendor its code. |

What the search did confirm: the two hard integrations you already run by hand (Cookidoo and Migros) have usable open-source clients, and HA has the entity types we need (`todo`, `calendar`, sensors, actionable notifications). So the new project is mostly orchestration, domain rules, and adapters, which is the part no one has built.

## 2. Your Home Assistant and homelab

Inspected via the Proxmox MCP (node `teodor`):

- **HA is HAOS**, VM 105 `haos12.3`, 2 cores, 7.8 GB RAM, **95 % memory used**. Running the planner inside HA is a bad idea on this box regardless of architecture.
- LXCs already present: `caddy` (109), `hermes`, `homey-shs`, `overseerr`, `media-server`, `tautulli`, `proxmox-backup-server`.
- Local tooling: Python 3.13, `uv` 0.13, `gh` (logged in as sbarkar), node 22. No Docker on this workstation.

**Recommendation:** standalone engine in a new LXC behind Caddy, plus a thin HACS integration in HA. Because HA is HAOS, an **HA add-on is also possible**; it is the same Docker image with an add-on manifest and can be done in Phase 6 for households without a Proxmox host. See ADR-0002.

## 3. Cookidoo

- **Library:** [`cookidoo-api`](https://github.com/miaucl/cookidoo-api) 0.19.0 (MIT, aiohttp, 168 stars, pushed 2026-10-22). It is what HA core's official Cookidoo integration uses, and Debian/Ubuntu package it under the HA team. Full method list verified locally: recipe search with locale/country/language filters, recipe details, shopping list (ingredient items + additional items, ownership flags), **calendar read/add/remove by date** (`get_recipes_in_calendar_week`, `add_recipes_to_calendar`, `remove_recipe_from_calendar`, custom-recipe variants), custom recipes CRUD, collections, subscription, devices, and appliance cook-state via push messages.
- That covers `RecipeSource` and the Cookidoo `MealPlanSink` ("My Week" = the calendar) completely. No new client needed.
- **Risk:** Cookidoo changed its login flow in May 2026; HA's integration broke for weeks (home-assistant/core#171792). Fixed in cookidoo-api 0.17.x, auth is now account-based not region-based. We must pin the library, keep recorded login fixtures, and surface auth failures as an HA repair issue rather than silently stalling.
- **Your current MCP:** `cookidoo-mcp` 1.1.1 via uvx (upstream is 1.2.0, pins `cookidoo-api <0.18`). We will not depend on it; the engine uses the library directly. The MCP remains useful for ad-hoc work.
- The HA core Cookidoo integration exposes the shopping list as `todo` entities and the meal plan as a `calendar`. Our integration should not duplicate it; ours is the *plan status, basket, in-store list and approval* surface.

## 4. Migros

There is no official API. Everything below is reverse-engineered mobile/web endpoints.

- **Your patched server:** `lewpgs/migros-mcp` 0.3.1 (MIT, TypeScript, 133 stars, last push 2026-05-03) installed as a Claude Desktop extension as `0.3.2-local.1` with your patch ("full login-form submission + clear password/OTP rejection errors"). It wraps [`migros-api-wrapper`](https://github.com/aliyss/migros-api-wrapper) 1.1.37 (MIT, pushed 2026-08-27) and adds a login chain: `login.migros.ch` email → password → TOTP → `/return` → `account.migros.ch` → OAuth authorize with PKCE → JWT. Your `~/Documents/Health/migros-trace/trace.txt` documents this chain with secrets scrubbed; it is a ready-made fixture.
- **Endpoints the wrapper knows** (hosts: `www.migros.ch`, `mobile-api-gateway.shop.migros.ch`, `login.migros.ch`, `account.migros.ch`): `onesearch-oc-seaapi/public/v5` (search), `product-display/public/v4` (details, price, nutrition), `shopping-list/public/v1` (lists, keyed by `shoppingListId`), `marketablestock/public/v2` (stock), `store-availability/public/v2`, `store/public/v1/stores`, Cumulus coupons, Migusto recipes.
- **What the MCP does not expose and we need:** multiple lists by ID (the wrapper has it, the MCP hides it behind "the basket"), delivery slots and the slot's end time, per-product deliverability for a postcode, minimum-order value, online vs in-store price distinction, promotions on the basket. These are exactly lessons 1, 2, 4, 5, 6 from running it by hand.
- **Recommendation (ADR-0003): native Python adapter**, porting the login chain and the handful of endpoints to `httpx`, with `curl_cffi` as a fallback transport if Cloudflare rejects the TLS fingerprint (masone's skill needed it; the Node server does not). Wrapping the Node MCP would add a Node runtime to the LXC and the add-on, would still need forking to expose the missing data, and makes recorded-fixture tests awkward. The patched MCP stays as the reference implementation and for cross-checking during `e2e-dry-run`.
- Login needs a TOTP seed; passkey-only accounts cannot log in headlessly. Session tokens are persisted (the server reports a few weeks between full logins). The engine must store only the session file, never the password, after first login.

## 5. Other stores (later)

- **Coop, Aldi, Lidl, Farmy, Denner, Volg:** search/promotion/stock endpoints are documented in swissgroceries-mcp's adapters (read for facts, do not copy code). Coop sits behind DataDome bot protection. No open-source basket or list client exists for any of them. Each would be a research spike before an adapter.
- Cookidoo's own "shoppable recipes" ordering exists only for US/DE/UK partners (Amazon Fresh, Instacart, Albertsons), not Switzerland.

## 6. Other appliance ecosystems (research only, as requested)

| Ecosystem | Finding | Verdict |
|---|---|---|
| Bosch Cookit (Home Connect) | Official developer API lists a "Cook Processor" appliance type with program start/stop, status events and rate limits (1 000 req/day). No recipe, collection or meal-plan endpoints; recipes live in the Home Connect app only. | Not usable as a `MealPlanSink`. Could at most read cook state. |
| Monsieur Cuisine Smart/Connect (Lidl) | Cloud via the Lidl app (Tuya-based). Community HA integration is read-only and relies on undocumented endpoints; deeper access needs a rooted device. Weekly planner and shopping list exist only in the app. | Not viable. |
| Kenwood (Cooking Chef XL, CookEasy+, kCook) | Two apps (Kenwood World, Kenwood & Me), no public or reverse-engineered API found. | Not viable. |
| Magimix Cook Expert | Nothing found at all. | Not viable. |
| Thermomix TM6/TM7 | Cookidoo calendar via cookidoo-api, verified. | Phase 2. |

Realistic second sinks are therefore software, not appliances: the **no-appliance sink** (HA calendar + Markdown/PDF export) in Phase 1, then **Mealie** and **Tandoor** (both have meal-plan and shopping-list REST APIs) when someone asks for them.

## 7. Name

Decided 2026-10-24: **Znacht** (ts-NAKHT), Swiss German for dinner. Full reasoning, the rejected candidates and the availability checks are in [ADR-0004](decisions/0004-project-name.md).

Short version: "Mealwise" is used by at least four unrelated apps; "Tischlein" is a Swiss food-rescue charity; "Provender" was free but too abstract; "Scran" has a 2025 UK trademark for meal-planning software. Znacht was free on PyPI and GitHub, `znacht.dev`/`.app` were unregistered, `znacht.ch` is a dormant 2001 registration with no site, and no product uses the word.

Namespace: PyPI `znacht`, package `znacht`, HA domain `znacht`, GitHub `sbarkar/znacht`, adapters `znacht-<adapter>`.

## 8. Things only you can answer before Phase 1

1. ~~Name~~ — decided: Znacht (ADR-0004).
2. ~~Where the engine runs~~ — decided: LXC behind Caddy (ADR-0002).
3. **Seed rules file:** `docs/seed/meal-planning-rules.md` is not on this machine. The "Health" Claude project is not reachable from here; please export it and drop it into that path (or paste it).
4. ~~Licence~~ — decided: Apache-2.0 (ADR-0005).
5. **Migros login:** continue with email + password + TOTP seed stored once in the engine's secrets, as the patched MCP does today? (Passkeys cannot be automated.)
6. ~~LLM provider~~ — decided: Anthropic API default, pluggable (ADR-0006). Model tier is configuration.

## Sources

- Mealie HA integration: https://www.home-assistant.io/integrations/mealie/
- Cookidoo HA integration: https://www.home-assistant.io/integrations/cookidoo/
- cookidoo-api: https://github.com/miaucl/cookidoo-api · docs https://miaucl.github.io/cookidoo-api/
- Cookidoo auth breakage: https://github.com/home-assistant/core/issues/171792
- cookidoo-mcp: https://pypi.org/project/cookidoo-mcp/
- migros-mcp: https://github.com/lewpgs/migros-mcp · migros-api-wrapper: https://github.com/aliyss/migros-api-wrapper
- migros-shopping-skill: https://github.com/masone/migros-shopping-skill
- swissgroceries-mcp: https://github.com/nicktcode/swissgroceries-mcp
- open-supermarkets (Migros PR): https://github.com/abracadabra50/open-supermarkets/pull/28
- myMeal: https://github.com/Amantux/mymeal · MealMCP: https://github.com/bobjansen/MealMCP
- Mealie: https://github.com/mealie-recipes/mealie · Tandoor: https://github.com/TandoorRecipes/recipes · KitchenOwl: https://github.com/TomBursch/kitchenowl
- Home Connect API: https://api-docs.home-connect.com/
- Monsieur Cuisine HA thread: https://community.home-assistant.io/t/monsieur-cuisine-smart/418522
- Migros minimum order: https://support.migros.ch/hc/en-us/articles/360014984259
- Cookidoo shoppable recipes: https://thespoon.tech/thermomix-users-can-now-order-ingredients-with-launch-of-shoppable-recipes-on-cookidoo/
- Tischlein deck dich (charity): https://www.horizont.net/schweiz/nachrichten/tischlein-deck-dich-denner-und-ip-suisse-setzen-ein-zeichen-der-solidaritaet-185192
