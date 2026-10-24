from __future__ import annotations

from collections.abc import Iterable, Sequence

from znacht.domain.recipe import Recipe, RecipeId
from znacht.ports.recipes import RecipeQuery


class MemoryRecipeSource:
    name = "memory"

    def __init__(self, recipes: Iterable[Recipe]) -> None:
        self._recipes = {r.id.key: r for r in recipes}

    async def search(self, query: RecipeQuery) -> Sequence[Recipe]:
        hits: list[Recipe] = []
        for r in self._recipes.values():
            if query.text and query.text.lower() not in r.title.lower():
                continue
            if query.tags and not query.tags <= r.tags:
                continue
            if any(r.contains(x) for x in query.exclude_ingredients):
                continue
            if (
                query.max_total_minutes is not None
                and r.total_minutes is not None
                and r.total_minutes > query.max_total_minutes
            ):
                continue
            if query.locales and r.locale not in query.locales:
                continue
            hits.append(r)
        hits.sort(key=lambda r: (-(r.rating or 0), r.title))
        return hits[: query.limit]

    async def get(self, recipe_id: RecipeId) -> Recipe:
        try:
            return self._recipes[recipe_id.key]
        except KeyError as exc:
            raise LookupError(f"unknown recipe {recipe_id}") from exc
