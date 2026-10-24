# Znacht — architecture (Phase 0 proposal)

Status: draft for review, 2026-10-24. Name confirmed as Znacht on 2026-10-24 (ADR-0004).

**Znacht** (ts-NAKHT) is Swiss German for dinner, the evening meal and the centre of the weekly food loop.

Znacht automates the weekly household food loop: plan the week under health, preference, capacity and pantry constraints; push the plan to where the household cooks; split groceries into an online basket and an in-store list; optimise every product for health first, then value; hand over to a human. It never checks out, pays or places an order.

## 1. Shape

```
┌──────────────────────────── Home Assistant (HAOS VM) ─────────────────────────────┐
│  custom_components/znacht  (HACS)                                                │
│   todo.online_basket  todo.instore_list  calendar.meal_plan                         │
│   sensor.basket_total  sensor.min_order  sensor.next_delivery  sensor.plan_status   │
│   actions: plan_week · optimize_products · apply_plan · update_pantry · refresh     │
│   actionable notification: "Plan ready: 3 switches save CHF 4.20 — Approve/Review"  │
└───────────────────────────────▲──────────────────────────────────────────────────┘
                                │ HTTPS (Caddy) + long-poll/SSE for status
┌───────────────────────────────┴──────────────────────────────────────────────────┐
│  Engine (Python 3.12+, FastAPI) — LXC on Proxmox, or the same image as an HA add-on │
│                                                                                     │
│   znacht (core)      domain · ports · planner · checker · splitter · optimiser   │
│        ▲                      ▲                        ▲                           │
│  entry points          entry points              entry points                      │
│   znacht-cookidoo    znacht-migros          znacht-llm-anthropic          │
│   (RecipeSource,        (GroceryStore)            (PlannerProvider)                │
│    MealPlanSink)                                                                    │
│   znacht-hasink      znacht-memory          znacht-llm-openai (later)     │
│   (MealPlanSink: HA      (in-memory fakes,                                          │
│    calendar + md/pdf)     used by tests)                                            │
└─────────────────────────────────────────────────────────────────────────────────┘
```

The core knows nothing about Cookidoo, Migros, Home Assistant or Anthropic. Every external system is an adapter behind a `typing.Protocol`, discovered through Python entry points, so a new store or recipe source ships as its own package.

## 2. Repository layout (uv workspace monorepo)

```
znacht/
├─ pyproject.toml                 # uv workspace root, ruff + mypy config
├─ Makefile                       # test, lint, e2e-dry-run, build-image
├─ packages/
│  ├─ znacht/                  # core: domain, ports, services, config, CLI
│  │   └─ src/znacht/
│  │       ├─ domain/             # Household, Member, HealthProfile, Rules, Pantry,
│  │       │                      # Recipe, MealPlan, IngredientNeed, Product,
│  │       │                      # ProductChoice, ShoppingPlan  (pydantic, frozen)
│  │       ├─ ports/              # RecipeSource, MealPlanSink, GroceryStore,
│  │       │                      # HealthProfileSource, PlannerProvider, Notifier
│  │       ├─ services/           # plan_week, check_constraints, split_groceries,
│  │       │                      # optimise_products, build_diff, apply
│  │       ├─ planner/            # prompt builders, JSON schema, deterministic checker
│  │       ├─ config/             # household YAML schema + loader + seed converter
│  │       ├─ registry.py         # entry-point discovery
│  │       └─ cli.py              # `znacht plan|optimise|diff|apply|pantry`
│  ├─ znacht-memory/           # in-memory fakes for every port + fixture catalogues
│  ├─ znacht-cookidoo/         # cookidoo-api based RecipeSource + MealPlanSink
│  ├─ znacht-migros/           # native httpx GroceryStore (login chain, lists, slots)
│  ├─ znacht-hasink/           # MealPlanSink: HA calendar + Markdown/PDF export
│  ├─ znacht-llm-anthropic/    # PlannerProvider on the Anthropic API
│  └─ znacht-engine/           # FastAPI app, job runner, state store (SQLite), auth
├─ custom_components/znacht/   # HACS integration (thin HTTP client, entities, actions)
├─ addon/                         # HA add-on manifest wrapping the engine image (Phase 6)
├─ deploy/                        # Dockerfile, compose, LXC notes, Caddy snippet
├─ tests/
│  ├─ contract/                   # one suite per port, parametrised over adapters
│  ├─ golden_week/                # the end-to-end fixture test
│  ├─ safety/                     # "no order, no payment" tests
│  └─ cassettes/                  # recorded HTTP (respx/VCR), secrets scrubbed
└─ docs/
   ├─ architecture.md  discovery.md
   ├─ decisions/                  # ADR log
   └─ seed/meal-planning-rules.md # your rules, converted into households/*.yaml
```

Core is `mypy --strict`; adapters are `mypy` with `strict` where practical. Python ≥ 3.12, `uv` for everything.

## 3. Ports (interfaces)

Sketch only; exact signatures are Phase 1 work. All async.

```python
class RecipeSource(Protocol):
    async def search(self, q: RecipeQuery) -> list[RecipeSummary]: ...
    async def get(
        self, recipe_id: RecipeId
    ) -> Recipe: ...  # ingredients, servings, rating, time, tags


class MealPlanSink(Protocol):
    async def read_week(self, week: Week) -> MealPlan: ...
    async def diff(self, plan: MealPlan) -> PlanDiff: ...  # dry-run, no writes
    async def apply(self, diff: PlanDiff) -> ApplyResult: ...  # only path that writes


class GroceryStore(Protocol):
    async def search(self, q: str, *, limit: int = 6) -> list[Product]: ...
    async def product(
        self, product_id: ProductId
    ) -> Product: ...  # price_online, price_store, unit_price, pack, nutrition, promos, coupons
    async def deliverability(
        self, ids: list[ProductId], postcode: str
    ) -> dict[ProductId, Deliverability]: ...
    async def delivery_slots(self, postcode: str) -> list[DeliverySlot]: ...  # start, end, cutoff
    async def minimum_order(self) -> Money: ...
    async def lists(self) -> list[ShoppingListRef]: ...  # always by explicit ID
    async def read_list(self, list_id: ListId) -> ShoppingList: ...
    async def diff_list(self, list_id: ListId, target: ShoppingList) -> ListDiff: ...
    async def apply_list(self, list_id: ListId, diff: ListDiff) -> ApplyResult: ...
    async def stock(self, ids: list[ProductId]) -> dict[ProductId, StockStatus]: ...

    # deliberately absent: checkout, order, pay, slot booking


class HealthProfileSource(Protocol):
    async def load(
        self, household: HouseholdId
    ) -> HealthProfile: ...  # YAML, or LLM-extracted lab PDF after user confirmation


class PlannerProvider(Protocol):
    async def propose(
        self, ctx: PlanningContext
    ) -> PlanProposal: ...  # LLM; output is validated by the checker, never trusted
    async def extract(
        self, doc: Document, schema: type[T]
    ) -> T: ...  # lab PDF → markers, pantry photo → items


class Notifier(Protocol):
    async def notify(self, event: PlanEvent) -> None: ...
```

`Product` carries `price_online` and `price_store` as separate optional fields, `pack_size` with unit, `deliverable: bool | None` (unknown until checked for a postcode), and `promotions`/`coupons`. `IngredientNeed` carries `needed_on: date`, which drives the online/in-store split.

## 4. Pipeline (one `plan_week` run)

1. **Load** household YAML, health profile, pantry, preferred products, rules.
2. **Propose** — the LLM returns a structured week (recipe IDs from `RecipeSource.search`, servings, notes). Prompt includes rules, dislikes, allergies, toddler-mild flag, capacity, pantry.
3. **Check** — the deterministic checker validates the proposal against `Rules` (fish ×2, red meat ×1, legumes ×2, no dill, toddler-mild, …) and recipe facts fetched from the source, not from the LLM. Fails → bounded re-prompt with the violation list; still fails → plan status `needs_input`.
4. **Explode** — recipes × servings → `IngredientNeed[]` with `needed_on`, scaled by recipe servings, minus pantry.
5. **Split** — given the chosen `DeliverySlot` (end time matters: a 21:00 Monday delivery cannot feed Monday dinner), anything needed on or before delivery day → in-store list; the rest → online candidates; non-deliverable items for the postcode → in-store; free-text items pass through.
6. **Select & optimise** — per need, pull 3–6 alternatives, apply the health filter (sat-fat for meat/dairy, sugar for yogurt/muesli, salt for tins, wholegrain for grains, no fat-level change for toddler dairy), then unit price, promotions, coupons. Switch if healthier-or-equal and cheaper; flag if healthier but pricier with the CHF delta; otherwise keep. Judge every switch by the change in basket total and revert if worse. Re-check stock after each switch. Persist accepted picks as preferred products.
7. **Minimum order** — if online total < minimum: move later-in-week deliverable items from the in-store list, add items the plan genuinely uses, else ask the household. Never pad with pantry staples. Freezer items add the CHF 20 box deposit to the displayed total.
8. **Diff** — produce a dry-run diff for every sink: meal-plan sink, online list, in-store list. Status → `needs_approval`, notification sent.
9. **Apply** — only on explicit `apply_plan`. Writes happen through `apply(diff)` methods; nothing else writes.

## 5. Safety gates

- No port has a checkout/order/payment method. A test asserts, by AST and by `inspect`, that no adapter defines or calls one.
- Every adapter's HTTP layer goes through one client wrapper with a **URL denylist** (`checkout`, `order`, `payment`, `pay`, `slot/book`, …) that raises before the request leaves; a test fires every recorded request through it.
- `apply` requires a `diff_id` produced in the same run and a user-initiated trigger (HA action or CLI `--yes`).
- Secrets: engine reads from env or a mounted secrets file; HA integration stores only the engine URL and token in its config entry. Session tokens are persisted; passwords are discarded after first login where the service allows.
- Logs scrub tokens, cookies and account identifiers.

## 6. Home Assistant integration

- Thin `custom_components/znacht` (HACS). It polls / subscribes to the engine and exposes:
  - `todo.znacht_online_basket`, `todo.znacht_instore_list` — two-way (ticking an item in HA marks it bought; adding a free-text item adds it to the plan's free-text list).
  - `calendar.znacht_meal_plan`.
  - `sensor.znacht_basket_total`, `sensor.znacht_minimum_order` (met / short by CHF), `sensor.znacht_next_delivery`, `sensor.znacht_plan_status` (`draft → needs_input → needs_approval → applying → applied → error`).
  - actions `znacht.plan_week`, `optimize_products`, `apply_plan`, `update_pantry` (photo URL or text), `refresh`.
- Notifications are sent by the engine through HA's REST API (`notify.*` with actions), so approval buttons call back into `apply_plan`.
- HA's own Cookidoo integration remains the owner of Cookidoo's shopping list and calendar entities; we do not duplicate them.
- Deployment (ADR-0002): engine in an LXC on `teodor` behind Caddy. Phase 6 additionally packages the same image as an HA add-on for HAOS users.

## 7. Testing

- **Unit + Hypothesis** for quantity scaling, pack rounding, the split rule (`needed_on` vs slot end), minimum-order top-up, and the switch/revert rule.
- **Contract suites** per port; `znacht-memory` fakes and every real adapter run the same tests.
- **Recorded HTTP** (respx cassettes) for Cookidoo and Migros; the Migros login trace you already captured becomes the first cassette. No live calls in CI.
- **Golden week**: seed rules + pantry fixture + fixture catalogues → plan satisfies rules, split is correct for a Monday 19:00–21:00 delivery, online ≥ minimum without staple padding.
- **Safety**: denylist and no-order tests above.
- **HA**: `pytest-homeassistant-custom-component`.
- `make e2e-dry-run`: real accounts, read-only, prints the diff.
- CI: GitHub Actions, `ruff`, `mypy --strict` on core.

## 8. Phase plan

| Phase | Deliverable | Exit criterion |
|---|---|---|
| 0 | this document, ADR-0001…0004, name, repo created | your go |
| 1 | core domain, ports, config schema, in-memory fakes, deterministic planner, checker, splitter, optimiser, CLI | **done 2026-10-24**: golden-week test green on fakes; seed-rules conversion follows once `docs/seed/meal-planning-rules.md` lands |
| 2 | `znacht-cookidoo` (RecipeSource + MealPlanSink) | contract suite + cassettes green; `e2e-dry-run` shows a correct diff against your My Week |
| 3 | `znacht-migros` (native) | contract suite + cassettes green; dry-run reproduces last week's hand-made split |
| 4 | `znacht-llm-anthropic`, prompt/schema, re-prompt loop, lab-PDF and pantry-photo extraction with confirmation | golden week green with the real planner on fixture catalogues |
| 5 | engine API, HACS integration, notifications | entities and actions working on your HA |
| 6 | Dockerfile, LXC runbook, Caddy snippet, HA add-on | one-command deploy on `teodor` |

Each phase ends with all tests, a summary, and a stop for your go.
