from __future__ import annotations

from enum import StrEnum

from pydantic import field_validator

from znacht.domain._base import Frozen
from znacht.domain.quantity import Quantity


class Category(StrEnum):
    """Coarse ingredient/product category. Drives the health filter and the split rules."""

    MEAT = "meat"
    POULTRY = "poultry"
    FISH = "fish"
    DAIRY = "dairy"
    YOGURT = "yogurt"
    MUESLI = "muesli"
    TINNED = "tinned"
    GRAIN = "grain"
    BAKERY = "bakery"
    PRODUCE = "produce"
    HERB = "herb"
    LEGUME = "legume"
    FROZEN = "frozen"
    PANTRY = "pantry"
    OTHER = "other"


class Spiciness(StrEnum):
    NONE = "none"
    MILD = "mild"
    HOT = "hot"


class Tag(StrEnum):
    """Well-known recipe tags the weekly rules count. Free-form tags are allowed too."""

    FISH = "fish"
    RED_MEAT = "red_meat"
    POULTRY = "poultry"
    LEGUMES = "legumes"
    VEGETARIAN = "vegetarian"
    FAMILY = "family"
    BREAKFAST = "breakfast"  # not a dinner: the timeline skips it when picking a day's dinner


def normalise_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


class Ingredient(Frozen):
    name: str
    quantity: Quantity
    category: Category = Category.OTHER
    staple: bool = False
    optional: bool = False
    raw: str | None = None

    @field_validator("name")
    @classmethod
    def _normalise(cls, value: str) -> str:
        return normalise_name(value)


class RecipeId(Frozen):
    """Identifies a recipe across sources. ``source`` is the adapter name."""

    source: str
    external_id: str

    @property
    def key(self) -> str:
        return f"{self.source}:{self.external_id}"

    def __str__(self) -> str:
        return self.key


class Recipe(Frozen):
    id: RecipeId
    title: str
    servings: int
    ingredients: tuple[Ingredient, ...]
    tags: frozenset[str] = frozenset()
    total_minutes: int | None = None
    active_minutes: int | None = None
    rating: float | None = None
    rating_count: int | None = None
    spiciness: Spiciness = Spiciness.NONE
    locale: str | None = None
    url: str | None = None

    @field_validator("servings")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("servings must be positive")
        return value

    def has_tag(self, tag: Tag | str) -> bool:
        return str(tag) in self.tags

    def ingredient_names(self) -> frozenset[str]:
        return frozenset(i.name for i in self.ingredients)

    def contains(self, name: str) -> bool:
        needle = normalise_name(name)
        return any(needle in i.name for i in self.ingredients)
