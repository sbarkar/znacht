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
    merged_from: tuple[str, ...] = ()  # keys of the per-day needs a merged need sums

    @property
    def key(self) -> str:
        """Identifies one need of one ingredient on one day; shopping lines trace back to it."""
        return f"{self.name}|{self.needed_on.isoformat()}|{self.quantity.base_unit}"

    @property
    def keys(self) -> tuple[str, ...]:
        return self.merged_from or (self.key,)
