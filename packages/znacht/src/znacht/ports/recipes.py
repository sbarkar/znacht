from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from znacht.domain._base import Frozen
from znacht.domain.recipe import Recipe, RecipeId


class RecipeQuery(Frozen):
    text: str | None = None
    tags: frozenset[str] = frozenset()
    exclude_ingredients: frozenset[str] = frozenset()
    max_total_minutes: int | None = None
    locales: tuple[str, ...] = ()
    limit: int = 50


@runtime_checkable
class RecipeSource(Protocol):
    """Where recipes come from. Ratings are a guide, not a filter."""

    name: str

    async def search(self, query: RecipeQuery) -> Sequence[Recipe]: ...

    async def get(self, recipe_id: RecipeId) -> Recipe: ...
