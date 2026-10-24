from __future__ import annotations

from datetime import date

from znacht.domain._base import Frozen
from znacht.domain.quantity import Quantity
from znacht.domain.recipe import Category, RecipeId


class IngredientNeed(Frozen):
    """A quantity of one ingredient needed on one date, after pantry deduction."""

    name: str
    quantity: Quantity
    needed_on: date
    category: Category = Category.OTHER
    staple: bool = False
    recipes: tuple[RecipeId, ...] = ()
