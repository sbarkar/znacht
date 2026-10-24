from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal

from znacht.domain.household import Household
from znacht.domain.needs import IngredientNeed
from znacht.domain.plan import MealPlan
from znacht.domain.quantity import Quantity, Unit
from znacht.domain.recipe import Category, Recipe, RecipeId


class _Acc:
    def __init__(self, quantity: Quantity, category: Category, staple: bool) -> None:
        self.quantity = quantity
        self.category = category
        self.staple = staple
        self.recipes: list[RecipeId] = []


def explode_needs(
    plan: MealPlan, recipes: Mapping[str, Recipe], household: Household
) -> list[IngredientNeed]:
    """Recipe ingredients, scaled by servings, aggregated per ingredient and date,
    minus what the pantry holds (pantry covers the earliest needs first)."""
    acc: dict[tuple[str, date, Unit], _Acc] = {}
    for meal in plan.meals:
        recipe = recipes.get(meal.recipe_id.key)
        if recipe is None:
            raise KeyError(f"recipe {meal.recipe_id} not in the recipe map")
        factor = Decimal(meal.servings) / Decimal(recipe.servings)
        for ing in recipe.ingredients:
            if ing.optional:
                continue
            qty = ing.quantity.scale(factor).to_base()
            key = (ing.name, meal.date, qty.unit)
            entry = acc.get(key)
            if entry is None:
                entry = _Acc(qty, ing.category, ing.staple)
                acc[key] = entry
            else:
                entry.quantity = entry.quantity + qty
                entry.staple = entry.staple and ing.staple
            entry.recipes.append(recipe.id)

    remaining = household.pantry.as_dict()
    needs: list[IngredientNeed] = []
    for (name, day, _unit), entry in sorted(acc.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        qty = entry.quantity
        have = remaining.get(name)
        if have is not None and have.compatible(qty):
            covered = Quantity(value=min(have.base_value, qty.base_value), unit=qty.unit)
            qty = qty.minus(covered)
            remaining[name] = have.minus(covered)
        if qty.is_zero:
            continue
        needs.append(
            IngredientNeed(
                name=name,
                quantity=qty,
                needed_on=day,
                category=entry.category,
                staple=entry.staple,
                recipes=tuple(entry.recipes),
            )
        )
    return apply_make_at_home(needs, household)


def merge_needs(needs: list[IngredientNeed]) -> list[IngredientNeed]:
    """Merge needs of the same ingredient into one, needed on the earliest date.

    Used per channel after the timing split, so packs are computed from the week's total
    rather than per day (three onions across three dinners is one bag, not three)."""
    merged: dict[tuple[str, Unit], IngredientNeed] = {}
    for need in needs:
        key = (need.name, need.quantity.base_unit)
        current = merged.get(key)
        if current is None:
            merged[key] = need.model_copy(update={"quantity": need.quantity.to_base()})
            continue
        merged[key] = current.model_copy(
            update={
                "quantity": current.quantity + need.quantity,
                "needed_on": min(current.needed_on, need.needed_on),
                "staple": current.staple and need.staple,
                "recipes": current.recipes + need.recipes,
            }
        )
    return sorted(merged.values(), key=lambda n: (n.needed_on, n.name))


def apply_make_at_home(needs: list[IngredientNeed], household: Household) -> list[IngredientNeed]:
    """Replace a bought dish (hummus, pesto) with its components when the household makes it."""
    if not household.make_at_home:
        return needs
    recipes_for = {m.dish: m for m in household.make_at_home}
    result: list[IngredientNeed] = []
    for need in needs:
        spec = recipes_for.get(need.name)
        if spec is None:
            result.append(need)
            continue
        for comp_name, comp_qty in spec.components:
            result.append(
                IngredientNeed(
                    name=comp_name,
                    quantity=comp_qty.to_base(),
                    needed_on=need.needed_on,
                    category=Category.OTHER,
                    staple=False,
                    recipes=need.recipes,
                )
            )
    return result
