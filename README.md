# Znacht

**Znacht** (*ts-NAKHT*) is Swiss German for dinner. It is a self-hosted planner that takes the whole
weekly food loop off your plate and puts it in Home Assistant: it plans the week's dinners for the
people who actually eat them, writes them to Cookidoo "My Week", fills your Migros lists, and stops
there. You approve every week; you place the order. **Znacht never checks out, never pays, never
places an order**, by design and enforced by a test.

> HACS installs the Home Assistant half of Znacht. The planning happens in a small engine that runs
> next to Home Assistant (as an add-on, an LXC or a container). Set up the engine first, then the
> integration: [Setup](#setup) walks through both.

## Why

Every week someone in the house answers the same questions: what are we eating, does it suit
everyone, do we have what we need, what do we order, what do we pick up in the shop, and is any of
it healthier or cheaper than what we usually buy. Znacht answers them in one pass and shows its work:

- **Plans for your household, not for an average one.** Likes and dislikes per person, allergies and
  banned ingredients, a toddler who needs mild food, "fish twice, red meat at most once", how long you
  can cook on a weekday, and what is already in the pantry.
- **Health first, then value, always explained.** Every product it picks is the healthiest sensible
  choice, then the best value; every switch shows its reason and the CHF difference.
- **Splits the groceries the way you actually shop.** An online basket for delivery and a store run
  for what is better or only available in the shop, grouped in the order you walk the aisles, with
  progress towards the delivery minimum.
- **My Week is the truth.** Dinners you put in Cookidoo by hand count. Znacht only fills the gaps, and
  everything it suggests stays a proposal until you approve it. Undo is one tap.
- **Lives where you already look.** Tonight's dinner on a dashboard, the shopping lists as Home
  Assistant to-do lists, the plan in a calendar, a notification when the week is ready.
- **Yours.** It runs on your hardware. Your household file, the database and your account sessions
  stay on it.

## What a week looks like

1. **Plan.** On Thursday (by hand, a button or an automation), Znacht plans the empty dinners of next
   week. Planning takes a minute or two in the background.
2. **Review.** Your phone gets "Znacht: plan ready" with the theme, the basket total and the number of
   swaps. Review opens the **Brief**: a card per dinner with minutes and cost per person, the money,
   every swap and flag with its reason, the online basket and the store run.
3. **Tweak.** Swap a dinner for one of the pre-checked alternatives, lock the ones you like, plan again.
4. **Approve.** One button writes the dinners to My Week and the lines to your two Migros lists.
   Nothing touches an outside account before this.
5. **Shop.** Finish the order in the Migros app or website (Znacht links to it). Walk the store run
   with the Groceries screen or the Home Assistant to-do list and tick things off.
6. **Cook.** The dashboard and the calendar say what is for dinner tonight and whether the food is
   here.

## What you get in Home Assistant

**The Znacht app in the sidebar.** Four phone-first screens:

- **Week**: Tonight (and tomorrow) at the top, then a rolling timeline of the coming days: planned,
  proposed, empty or past, with whether the food for each day is listed or not. One "Review" banner per
  proposed week and "Plan the gaps" for the empty days.
- **Groceries**: opens on the week you are shopping for. Online basket and store run, the store's own
  availability, move a line between them, add anything, tick off.
- **Household**: people, dislikes, allergies, weekly rules, health rules, the pantry (also from a
  photo). Edits go back into your household YAML with your comments kept.
- **Connections**: every recipe source, store and planner as a card, with its state.

**Entities** (all on one *Znacht* device):

| Entity | What it shows |
|---|---|
| `calendar` Meal plan | every planned dinner, including the ones you added in Cookidoo yourself |
| `todo` Online basket | the Migros delivery list; tick or add items |
| `todo` Store run | the in-store list; tick or add items |
| `sensor` Tonight's dinner | the dinner for today |
| `sensor` Plan status | `idle`, `planning`, `needs_approval`, `applied`, `needs_input`, `reverted`, `error` |
| `sensor` Open findings | reconciliation findings not yet fixed or overridden: buying more than a pack beyond the week's need across both lists, a product on both lists, a line no recipe asked for. Approve waits until it is 0; the messages are in its attributes |
| `sensor` Unplanned days | count of empty days ahead; the dates are in its attributes |
| `sensor` Online basket total, Minimum order | CHF, so you can see how far the basket is from free delivery |
| `sensor` Next delivery | the planned delivery slot |
| `sensor` Savings this week, Savings since start | what the product switches saved |

**Actions** (services):

| Action | Does |
|---|---|
| `znacht.plan_week` | plan a week (`week`: any date in it, default next week). Proposes only; writes nothing outside. |
| `znacht.optimize_products` | re-run the grocery split and the product picks |
| `znacht.apply_plan` | write the approved plan to My Week and the lists (`run_id`, default the latest). The only action that writes to Cookidoo or Migros. |
| `znacht.update_pantry` | set pantry quantities, e.g. `{"rice": "1 kg", "olive oil": "0"}` (`0` removes) |
| `znacht.reconcile` | run the reconciliation check (`run_id`); `fix` a list of finding IDs (quantities computed again from the week's need), `overrides` finding ID → reason to buy it anyway (logged). On a sent plan it checks the live Migros lists. Returns the findings |
| `znacht.refresh` | re-read the Migros lists |

## What it works with today

| Part | Today | Planned |
|---|---|---|
| Recipes and meal plan | **Cookidoo** (Thermomix): recipe search and My Week | Mealie, Tandoor |
| Groceries | **Migros Online** (Switzerland) | Coop, Farmy, Aldi, Lidl |
| Planner | **Claude** (Anthropic API, recommended), or the built-in rule-based planner | OpenAI-compatible, Ollama |

So for real weeks Znacht needs a **Cookidoo** subscription and a **Migros** account. Without them it
runs on a built-in sample catalogue and store, which is good for trying it out and not for cooking. The
Migros adapter talks to the same endpoints the web shop uses; there is no official API, so a change on
Migros' side can break it until Znacht is updated. Every request passes a guard that refuses checkout,
order and payment paths before they leave the machine.

## Setup

You need Home Assistant 2025.6 or newer. On Home Assistant OS everything happens in Home Assistant,
with forms and taps; no file editor, no command line.

### 1. Install Znacht from HACS

1. HACS → ⋮ → Custom repositories → add `https://github.com/sbarkar/znacht` as type **Integration**.
2. Find **Znacht** in HACS, download it, restart Home Assistant.
3. Settings → Devices & services → Add integration → **Znacht** → **Run Znacht here in Home Assistant**.
4. Enter your accounts. Each one is optional; leave it empty and that part runs on sample data, so you
   can try Znacht first and add the accounts later under **Configure**.
   - **Cookidoo**: email and password. The password is used once; after that a token is kept.
   - **Migros**: email and password. Only if your account uses an authenticator app, also its setup
     key (not the 6-digit code).
   - **Claude**: an Anthropic API key, for more varied weeks and pantry by photo. Without one, the
     built-in planner is used.
5. Znacht installs and starts its add-on (the first time takes a few minutes) and checks each account.
   A password that does not work comes back on its own field.

Then open **Znacht** in the sidebar. A short Welcome walks you through your household: who eats, how
you cook, your delivery postcode and slot, and the two Migros lists to fill, picked from your account.

### Already running the engine elsewhere?

Choose **I already run the Znacht engine on another machine** in step 3 and enter its URL and API
token. That is also the only choice on Home Assistant Container or Core, which have no add-ons. To run
the engine yourself:

- **Proxmox LXC** (what the household that built it runs). One script creates a Debian container and
  installs the engine as a systemd service: [deploy/lxc/README.md](https://github.com/sbarkar/znacht/blob/main/deploy/lxc/README.md).
- **Docker / Compose** (a NAS, any box). Copy [`deploy/.env.example`](https://github.com/sbarkar/znacht/blob/main/deploy/.env.example) to
  `deploy/.env` and fill it in. Seed the data volume with the example household once, then start the
  engine:

  ```bash
  docker compose -f deploy/compose.yaml run --rm --no-deps znacht cp /app/household.example.yaml /data/household.yaml
  docker compose -f deploy/compose.yaml up -d
  ```

  The image is `ghcr.io/sbarkar/znacht`.

Check it is up with `curl http://<engine>:8787/healthz`. The app's Welcome then sets up the household the
same way. The add-on on its own (without HACS) is described in
[the add-on docs](https://github.com/sbarkar/znacht/blob/main/addon/znacht/DOCS.md).

> With an engine outside Home Assistant: if you open Home Assistant over HTTPS (Nabu Casa, a reverse
> proxy), the sidebar app can only load an engine that is also on HTTPS: put the engine behind your proxy
> (a Caddy snippet is in [`deploy/caddy/`](https://github.com/sbarkar/znacht/blob/main/deploy/caddy/Caddyfile.snippet))
> and use that URL in the integration.

### Notifications (optional)

Give the engine a Home Assistant long-lived access token (`ZNACHT_HA_URL`, `ZNACHT_HA_TOKEN`) and your
phone's notify service without the `notify.` prefix (`ZNACHT_HA_NOTIFY=mobile_app_<your_phone>`). The
add-on only needs `ha_notify`; it reaches Home Assistant by itself, and its links open the Znacht panel in
the Home Assistant app.

You then get "plan ready" (with Approve and Review buttons; while a reconciliation finding is open the
notification lists it first, above the savings, and offers only Review) and "needs a hand" when a plan could not be
completed. Review opens the Brief. The Approve button fires a `mobile_app_notification_action` event
with action `ZNACHT_APPROVE` and does nothing by itself; Znacht fires `znacht_plan_ready` and
`znacht_needs_input` events (with `run_id` and `url`) for your own automations.

### Plan your first week

Open Znacht from the sidebar and press **Plan the gaps** on the week you want, or call
`znacht.plan_week`. When the plan is ready, Review, change what you like, Approve.

To make it a habit, plan every Thursday evening:

```yaml
automation:
  - alias: "Znacht: plan next week"
    triggers:
      - trigger: time
        at: "18:00:00"
    conditions:
      - condition: time
        weekday: [thu]
    actions:
      - action: znacht.plan_week
```

And show tonight's dinner on a dashboard with an entity card on `sensor.znacht_tonight_s_dinner`, the
`todo` cards for the two lists and a calendar card on the meal plan.

## Your household

One YAML file describes who eats and how. You never have to open it: the app's Welcome writes it the
first time, and the Household screen edits it afterwards (people, rules, pantry, delivery slot, the
Migros lists) and keeps your comments. For those who like files, the engine validates it on load. A full example with every option explained:
[examples/household.example.yaml](https://github.com/sbarkar/znacht/blob/main/examples/household.example.yaml).

```yaml
id: home
name: Our household
members:
  - name: Anna
    age_group: adult
    dislikes: [dill]
  - name: Leo
    age_group: toddler        # implies mild food
rules:
  dinners_per_week: 7
  min_per_week: {fish: 2, legumes: 2}
  max_per_week: {red_meat: 1}
  max_total_minutes_weekday: 60
pantry:
  rice: 1 kg
  olive oil: 500 ml
delivery:
  postcode: "8000"
store_lists:                  # the IDs of your two Migros lists
  online: <list id>
  in_store: <list id>
```

Health rules and markers can be typed in, or drafted from a lab report: `znacht extract lab report.pdf`
writes a draft that you review and merge; nothing extracted is used without your confirmation.

## Maintenance

**Updates.** Integration: HACS offers each new release; update and restart Home Assistant. Engine:
add-on updates appear in the add-on store; on an LXC, run `pct exec <vmid> -- /opt/znacht/deploy/lxc/install.sh`;
with Compose, `docker compose pull && docker compose up -d`. Keep the engine and the integration on
the same release.

**Backups.** Everything stateful is in the engine's data folder (`/var/lib/znacht` on the LXC, the
add-on's config folder, the `znacht-data` volume): the SQLite database with every run and the
savings, the household YAML, the Cookidoo token and the Migros session. Home Assistant backups include
the add-on; Proxmox backups include the LXC. Your accounts' secrets are in the env file or the add-on
options.

**Moving the engine.** Settings → Devices & services → Znacht → ⋮ → Reconfigure with the new URL and
token. Entities, history and the sidebar panel follow.

**When something is off.**

| Symptom | Likely cause and fix |
|---|---|
| Integration: "Could not reach the engine" | wrong URL or port, the engine is stopped, or a firewall between them; check `/healthz` from the Home Assistant host |
| "The token was rejected" | the token in the integration differs from `ZNACHT_API_TOKEN`; Reconfigure |
| "Znacht is busy with the previous request" | a plan is still running; wait a minute |
| Plan status `needs_input` | the rules could not all be met (too few fish recipes, too little time); the Week screen and the Brief say which. Loosen a rule or lock a dinner and plan again |
| Migros lists stop updating | the Migros session expired: make sure email, password and TOTP secret are set and restart the engine, or Migros changed an endpoint (check the issues) |
| Cookidoo errors after a password change | delete `cookidoo-token.json` in the data folder, set the new password, restart |
| Sidebar panel stays blank | Home Assistant on HTTPS and the engine on HTTP; see the HTTPS note in Setup (not an issue with the add-on) |
| Add-on: Znacht not offered as discovered | add it by hand with `http://<add-on hostname>:8787` (Info page) and the token in `.api_token` in the add-on's config folder |

Engine logs: the add-on's Log tab, `journalctl -u znacht` on the LXC, `docker logs znacht`.

## Safety and privacy

- No checkout, order or payment endpoint exists, and a test fails the build if one appears. The store
  adapter refuses those paths at the request level.
- Nothing is written to Cookidoo or Migros until you approve, and the Review screen shows what
  approving would remove from My Week before you do.
- Account credentials live in the engine's env file or the add-on options, never in the household
  file. Only the planner (Anthropic) sees your household's rules and the candidate recipes, and only if
  you choose the Claude planner.

## Status

Znacht is young (0.x) and used every week by the household that built it. The engine, the app, the
Brief, the Cookidoo and Migros adapters, the Claude planner and the Home Assistant integration are
done; next on the [roadmap](https://github.com/sbarkar/znacht/blob/main/docs/roadmap.md): planning any date range, reading placed Migros orders so
"arriving Monday" is a fact, voice through Assist, and more stores and recipe sources.

## For developers

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-packages
make check        # ruff, mypy --strict, pytest
make test-ha      # the Home Assistant integration's tests
make demo         # plan a week on the sample household, no accounts needed
```

Run the engine locally on the sample adapters and open the app:

```bash
ZNACHT_HOUSEHOLD=examples/household.example.yaml ZNACHT_DATA_DIR=/tmp/znacht uv run znacht-engine
# then open http://localhost:8787/app and press "Plan the gaps"
```

The core knows nothing about any store, recipe platform or appliance. Each one is an adapter behind
a typed port, discovered through Python entry points, so a new store or recipe source ships as its
own package:

| Port | Adapters |
|---|---|
| `RecipeSource` | `cookidoo`, `memory` (sample catalogue) |
| `MealPlanSink` | `cookidoo` (My Week), `memory` (kept in the engine, shown in the HA calendar) |
| `GroceryStore` | `migros`, `memory` |
| `PlannerProvider` | `anthropic`, `rule_based` |

More: [architecture](https://github.com/sbarkar/znacht/blob/main/docs/architecture.md), [engine API and settings](https://github.com/sbarkar/znacht/blob/main/packages/znacht-engine/README.md),
[decision log](https://github.com/sbarkar/znacht/tree/main/docs/decisions/), [roadmap](https://github.com/sbarkar/znacht/blob/main/docs/roadmap.md), [contributing and releases](https://github.com/sbarkar/znacht/blob/main/CONTRIBUTING.md).

## Licence

Apache-2.0. See [LICENSE](https://github.com/sbarkar/znacht/blob/main/LICENSE).
