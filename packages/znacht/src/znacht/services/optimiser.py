"""Product selection: health filter first, then value. Every decision carries its reason."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from znacht.domain.household import Household
from znacht.domain.money import Money, total
from znacht.domain.needs import IngredientNeed
from znacht.domain.product import Channel, Product
from znacht.domain.recipe import Category
from znacht.domain.shopping import ProductChoice
from znacht.services.packs import packs_needed

_WORST: Final = Decimal("Infinity")

LOWER_IS_BETTER: Final[dict[Category, str]] = {
    Category.MEAT: "saturated_fat_g",
    Category.POULTRY: "saturated_fat_g",
    Category.DAIRY: "saturated_fat_g",
    Category.YOGURT: "sugar_g",
    Category.MUESLI: "sugar_g",
    Category.TINNED: "salt_g",
}

_TODDLER_FAT_TOLERANCE: Final = Decimal("0.5")


def health_metric(product: Product) -> str | None:
    if product.category in LOWER_IS_BETTER:
        return LOWER_IS_BETTER[product.category]
    if product.category == Category.GRAIN:
        return "wholegrain"
    return None


def health_rank(product: Product) -> Decimal:
    """Lower is healthier. Unknown values rank worst so the filter never rewards missing data."""
    metric = health_metric(product)
    if metric is None:
        return Decimal(0)
    if metric == "wholegrain":
        return Decimal(0) if product.wholegrain else Decimal(1)
    if product.nutrition is None:
        return _WORST
    value: Decimal | None = getattr(product.nutrition, metric)
    return value if value is not None else _WORST


def line_total(product: Product, need: IngredientNeed, channel: Channel) -> Money | None:
    price = product.price(channel)
    if price is None:
        return None
    packs = packs_needed(need.quantity, product.pack)
    line = price * packs - total([c.discount for c in product.coupons], price.currency)
    return line if not line.is_negative else Money.zero(price.currency)


def _toddler_dairy_ok(candidate: Product, baseline: Product | None, household: Household) -> bool:
    """Never change the fat level of dairy a toddler eats."""
    if baseline is None or not household.has_toddler:
        return True
    if baseline.category not in (Category.DAIRY, Category.YOGURT):
        return True
    if baseline.nutrition is None or baseline.nutrition.fat_g is None:
        return candidate.id == baseline.id
    if candidate.nutrition is None or candidate.nutrition.fat_g is None:
        return False
    return abs(candidate.nutrition.fat_g - baseline.nutrition.fat_g) <= _TODDLER_FAT_TOLERANCE


def choose_product(
    need: IngredientNeed,
    candidates: Sequence[Product],
    household: Household,
    channel: Channel,
    baseline: Product | None = None,
) -> ProductChoice | None:
    """Pick a product for one need.

    Switch if a candidate is healthier-or-equal and cheaper than the baseline. Flag, but keep,
    if the healthiest option is pricier, showing the difference. Otherwise keep the baseline.
    Without a baseline: best health rank, then cheapest line total.
    """
    usable = [
        c
        for c in candidates
        if line_total(c, need, channel) is not None and _toddler_dairy_ok(c, baseline, household)
    ]
    if (
        baseline is not None
        and line_total(baseline, need, channel) is not None
        and all(c.id != baseline.id for c in usable)
    ):
        usable.append(baseline)
    if not usable:
        return None

    def cost(p: Product) -> Money:
        value = line_total(p, need, channel)
        assert value is not None
        return value

    def choice(p: Product, reason: str, **extra: object) -> ProductChoice:
        return ProductChoice(
            need_name=need.name,
            product=p,
            packs=packs_needed(need.quantity, p.pack),
            needed_on=need.needed_on,
            channel=channel,
            reason=reason,
            baseline_product_id=baseline.id if baseline else None,
            **extra,
        )

    healthiest = min(usable, key=lambda p: (health_rank(p), cost(p).amount, p.id))

    if baseline is None or line_total(baseline, need, channel) is None:
        return choice(healthiest, f"best {health_metric(healthiest) or 'option'}, then cheapest")

    base_cost = cost(baseline)
    base_rank = health_rank(baseline)
    equal_or_better = [p for p in usable if health_rank(p) <= base_rank]
    cheapest_ok = min(equal_or_better, key=lambda p: (cost(p).amount, health_rank(p), p.id))

    chosen = baseline
    reason = "kept preferred product"
    extra: dict[str, object] = {}
    if cheapest_ok.id != baseline.id and cost(cheapest_ok) < base_cost:
        chosen = cheapest_ok
        delta = cost(cheapest_ok) - base_cost
        reason = f"healthier-or-equal and cheaper than {baseline.name}: saves {-delta}"
        extra = {"switched": True, "delta_vs_baseline": delta}

    if health_rank(healthiest) < health_rank(chosen) and cost(healthiest) > cost(chosen):
        delta = cost(healthiest) - cost(chosen)
        extra.update(
            {
                "flagged": True,
                "suggested_alternative": healthiest,
                "delta_vs_baseline": extra.get("delta_vs_baseline", delta),
            }
        )
        reason += f"; {healthiest.name} is healthier for {delta} more"
    return choice(chosen, reason, **extra)
