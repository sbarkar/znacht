"""The Znacht Brief: one page that tells the household what the week is, what it costs,
what changed and why, and asks for one tap. Pure view-model code; the template renders it."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from znacht.domain.money import Money, total
from znacht.domain.product import Channel
from znacht.domain.recipe import Category, Recipe
from znacht.domain.shopping import ProductChoice
from znacht.services.pipeline import WeekResult

# The order you walk a Swiss supermarket: produce by the door, frozen last so it stays frozen.
WALK_ORDER: tuple[tuple[str, tuple[Category, ...]], ...] = (
    ("Fruit & veg", (Category.PRODUCE, Category.HERB)),
    ("Bakery", (Category.BAKERY,)),
    ("Dairy & eggs", (Category.DAIRY, Category.YOGURT)),
    ("Meat & fish", (Category.MEAT, Category.POULTRY, Category.FISH)),
    (
        "Tins, grains & pantry",
        (
            Category.TINNED,
            Category.GRAIN,
            Category.LEGUME,
            Category.MUESLI,
            Category.PANTRY,
            Category.OTHER,
        ),
    ),
    ("Frozen", (Category.FROZEN,)),
)


@dataclass
class DinnerCard:
    date: str
    weekday: str
    title: str
    recipe_id: str
    minutes: int | None
    tags: list[str]
    note: str | None
    cost_per_person: Money | None
    in_store_day: bool


@dataclass
class SwapCard:
    need: str
    chosen: str
    reason: str
    kind: str  # "switch" | "flag" | "kept"
    delta: Money | None
    alternative: str | None


@dataclass
class Aisle:
    name: str
    lines: list[ProductChoice] = field(default_factory=list)


@dataclass
class Brief:
    run_id: int
    status: str
    week_label: str
    theme: str
    chef_note: str
    dinners: list[DinnerCard]
    online: list[ProductChoice]
    aisles: list[Aisle]
    free_text: list[str]
    pantry_check: list[str]
    swaps: list[SwapCard]
    online_subtotal: Money
    deposit: Money
    online_total: Money
    minimum_order: Money
    meets_minimum: bool
    shortfall: Money
    in_store_total: Money
    savings: Money
    slot_label: str | None
    notes: list[str]
    violations: list[str]
    lifetime_savings: Money
    checkout_url: str | None
    plan_removes: list[str]


def _title(recipes: dict[str, Recipe], key: str) -> str:
    return recipes[key].title if key in recipes else key.split(":", 1)[-1]


def _split_rationale(rationale: str) -> tuple[str, str]:
    if ":" in rationale and len(rationale.split(":", 1)[0]) <= 40:
        theme, note = rationale.split(":", 1)
        return theme.strip(), note.strip()
    return "This week", rationale.strip()


def _cost_per_recipe(result: WeekResult) -> dict[str, Money]:
    """Attribute each list line's cost to the recipes that need it, split evenly."""
    recipes_for_need: dict[str, list[str]] = defaultdict(list)
    for need in result.needs:
        for rid in need.recipes:
            if rid.key not in recipes_for_need[need.name]:
                recipes_for_need[need.name].append(rid.key)
    cost: dict[str, Money] = defaultdict(Money.zero)
    for line in (*result.shopping.online, *result.shopping.in_store):
        owners = recipes_for_need.get(line.need_name, [])
        if not owners:
            continue
        share = Money(amount=line.line_total().amount / Decimal(len(owners)))
        for key in owners:
            cost[key] = cost[key] + share
    return cost


def build_brief(
    run_id: int,
    result: WeekResult,
    recipes: dict[str, Recipe],
    *,
    lifetime_savings: Money,
    checkout_url: str | None = None,
) -> Brief:
    s = result.shopping
    theme, note = _split_rationale(result.rationale)
    per_recipe = _cost_per_recipe(result)
    servings = max(1, result.plan.meals[0].servings) if result.plan.meals else 1
    delivery_day = s.slot.delivery_day if s.slot else None
    dinners = [
        DinnerCard(
            date=m.date.isoformat(),
            weekday=m.date.strftime("%A"),
            title=recipes[m.recipe_id.key].title
            if m.recipe_id.key in recipes
            else m.recipe_id.external_id,
            recipe_id=m.recipe_id.key,
            minutes=recipes[m.recipe_id.key].total_minutes if m.recipe_id.key in recipes else None,
            tags=sorted(recipes[m.recipe_id.key].tags) if m.recipe_id.key in recipes else [],
            note=m.note,
            cost_per_person=(
                Money(amount=per_recipe[m.recipe_id.key].amount / Decimal(servings))
                if m.recipe_id.key in per_recipe
                else None
            ),
            in_store_day=delivery_day is not None and m.date <= delivery_day,
        )
        for m in result.plan.meals
    ]
    swaps = [
        SwapCard(
            need=c.need_name,
            chosen=c.product.name,
            reason=c.reason,
            kind="switch" if c.switched else "flag",
            delta=c.delta_vs_baseline,
            alternative=c.suggested_alternative.name if c.suggested_alternative else None,
        )
        for c in (*s.online, *s.in_store)
        if c.switched or c.flagged
    ]
    aisles: list[Aisle] = []
    for name, cats in WALK_ORDER:
        lines = [c for c in s.in_store if c.product.category in cats]
        if lines:
            aisles.append(Aisle(name=name, lines=sorted(lines, key=lambda c: c.product.name)))
    slot_label = None
    if s.slot:
        slot_label = f"{s.slot.start:%A %d %b, %H:%M}–{s.slot.end:%H:%M}"
    return Brief(
        run_id=run_id,
        status=str(result.status),
        week_label=f"Week of {result.week.start:%d %B %Y}",
        theme=theme,
        chef_note=note,
        dinners=dinners,
        online=sorted(s.online, key=lambda c: (c.product.category, c.product.name)),
        aisles=aisles,
        free_text=list(s.free_text),
        pantry_check=list(s.pantry_check),
        swaps=swaps,
        online_subtotal=s.online_subtotal,
        deposit=s.deposit,
        online_total=s.online_total,
        minimum_order=s.minimum_order,
        meets_minimum=s.meets_minimum,
        shortfall=s.shortfall,
        in_store_total=s.in_store_total,
        savings=s.savings,
        slot_label=slot_label,
        notes=list(result.notes),
        violations=[str(v) for v in result.violations],
        lifetime_savings=lifetime_savings,
        checkout_url=checkout_url,
        plan_removes=[
            f"{m.date:%a %d.%m}: {_title(recipes, m.recipe_id.key)}"
            for m in (result.plan_diff.remove if result.plan_diff else ())
        ],
    )


def price_rows(result: WeekResult) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for c in (*result.shopping.online, *result.shopping.in_store):
        for channel in (Channel.ONLINE, Channel.STORE):
            price = c.product.price(channel)
            if price is not None:
                rows.append((str(c.product.id), str(channel), str(price.amount)))
    return rows


def lifetime(ledger: list[dict[str, str]]) -> Money:
    return total([Money.chf(row["savings"]) for row in ledger])
