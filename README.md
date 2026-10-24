# Znacht

**Znacht** (*ts-NAKHT*) is Swiss German for dinner. It is also a self-hosted engine that runs a household's weekly food loop and plugs into Home Assistant:

1. **Plan** the week's meals within the household's constraints: health targets, people's likes and dislikes, cooking capacity, and what is already in the pantry.
2. **Push** the plan to where the household cooks. For a Thermomix household that is Cookidoo "My Week"; for everyone else, a Home Assistant calendar and a printable week.
3. **Split** the groceries into an online delivery basket and an in-store list, based on what can be delivered and when each ingredient is needed.
4. **Optimise** every product for health first, then value, with every switch explained.
5. **Hand over** to a human. Znacht never checks out, never pays, never places an order. By design, and enforced by a test.

The core knows nothing about any store, recipe platform or appliance. Each one is an adapter behind a typed port, discovered through Python entry points, so a new store or recipe source can ship as its own package.

| Port | First adapter | Later |
|---|---|---|
| `RecipeSource` | Cookidoo | Mealie, Tandoor, web recipes |
| `MealPlanSink` | Cookidoo My Week (Thermomix), HA calendar + Markdown export | Mealie, Tandoor |
| `GroceryStore` | Migros (CH) | Coop, Farmy, Aldi, Lidl |
| `PlannerProvider` | Anthropic API (+ a built-in deterministic planner) | OpenAI-compatible, Ollama |
| `HealthProfileSource` | YAML, lab-report PDF with confirmation | |

## The app

The engine serves the Znacht app at `/app`, and the Home Assistant integration puts it in the sidebar. Four screens, phone-first: **Week** (tap a dinner to swap it for a pre-checked alternative, lock it, plan again), **Groceries** (progress to the minimum order, online basket and store run with the store's own availability flags, move lines between them, tick off, add anything, approve, undo), **Household** (people, dislikes, allergies, weekly rules, health rules, pantry by photo; edits go back into your YAML with comments kept), **Connections** (every recipe source, store and planner as a card). No build step: vendored htm + preact.

## The Znacht Brief

Every plan ends in one page: the week's theme and the chef's note, a card per dinner with minutes and cost per person, the money (basket, minimum order, store run, savings this week and since the start), every swap and flag with its reason and the CHF difference, the online basket, the store run grouped in the order you walk the shop, and one button: **Approve**. Your phone gets an actionable notification; Review opens the Brief. After approval the page links to the store's own basket. Znacht never pays.

## Status

Phase 1 done: core domain, ports, deterministic planner, constraint checker, grocery split, product optimiser, in-memory fakes, and the golden-week test, all green. Try it without any account:

```bash
uv run znacht demo --household examples/household.example.yaml --week 2026-10-26
```

Phase 2 done: the Cookidoo adapter (`znacht-cookidoo`) searches recipes, maps them to the domain, and reads and writes My Week. Read-only check against your account:

```bash
ZNACHT_COOKIDOO_EMAIL=you@example.com ZNACHT_COOKIDOO_PASSWORD=... make e2e-dry-run
```

Phase 3 done: the native Migros adapter (`znacht-migros`) with both channel prices, nutrition, lists by ID and learned availability.

Phase 4 done: Claude as the planner (`znacht-llm-anthropic`) with structured outputs, plus `znacht extract lab report.pdf` and `znacht extract pantry photo.jpg`, which write a draft you confirm before anything is used.

Phase 5 done: the engine (`znacht-engine`, FastAPI + SQLite) with the Brief and a JSON API, and the Home Assistant integration (`custom_components/znacht`, HACS) with two todo lists, a meal-plan calendar, sensors and services.

Phase 6: `deploy/lxc/` installs the engine in a Proxmox LXC as a systemd service (create, install, bundle the secrets over, restore); `deploy/` also has a Docker image and compose file, the Caddy snippet, and `addon/` packages the image for HAOS.

```bash
ZNACHT_HOUSEHOLD=examples/household.example.yaml ZNACHT_DATA_DIR=/tmp/znacht uv run znacht-engine
curl -X POST localhost:8787/api/plan_week && open http://localhost:8787/brief
``` See [docs/architecture.md](docs/architecture.md) and the [decision log](docs/decisions/).

## Development

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-packages
make check        # ruff, mypy --strict, pytest
```

## Licence

Apache-2.0. See [LICENSE](LICENSE).
