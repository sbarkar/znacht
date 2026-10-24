from __future__ import annotations

from collections.abc import Sequence

from cookidoo_api import CookidooException

from znacht.domain.recipe import Recipe, RecipeId
from znacht.ports.recipes import RecipeQuery
from znacht_cookidoo.client import SOURCE, CookidooClient
from znacht_cookidoo.mapping import recipe_from_details, summary_from_hit


class CookidooRecipeSource:
    """Recipe search and details from Cookidoo.

    ``search`` returns summaries with full ingredients fetched per hit (Cookidoo's search
    only gives titles), capped at ``query.limit``. Recipe IDs are global across locales,
    so ``query.locales`` fans the search out and merges by ID.
    """

    name = SOURCE

    def __init__(self, client: CookidooClient, *, locale: str = "en", details: bool = True) -> None:
        self._client = client
        self._locale = locale
        self._details = details

    async def search(self, query: RecipeQuery) -> Sequence[Recipe]:
        locales = list(query.locales) or [self._locale]
        exclude = sorted(query.exclude_ingredients) or None
        seen: dict[str, Recipe] = {}
        for locale in locales:
            result = await self._client.search_recipes(
                query.text,
                locale=locale,
                exclude_ingredients=exclude,
                total_time=query.max_total_minutes * 60 if query.max_total_minutes else None,
                page_size=query.limit,
            )
            for hit in result.recipes:
                if hit.id and hit.id not in seen:
                    seen[hit.id] = summary_from_hit(hit, locale)
                if len(seen) >= query.limit:
                    break
        recipes = list(seen.values())[: query.limit]
        if not self._details:
            return recipes
        full: list[Recipe] = []
        for recipe in recipes:
            try:
                full.append(await self.get(recipe.id))
            except LookupError:
                continue
        return full

    async def get(self, recipe_id: RecipeId) -> Recipe:
        if recipe_id.source != SOURCE:
            raise LookupError(f"{recipe_id} is not a Cookidoo catalogue recipe")
        try:
            details = await self._client.get_recipe_details(recipe_id.external_id)
        except CookidooException as exc:
            raise LookupError(f"Cookidoo recipe {recipe_id.external_id}: {exc}") from exc
        return recipe_from_details(details, self._locale)
