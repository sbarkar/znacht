"""The slice of cookidoo-api the adapters use, as a Protocol so tests can fake it."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from cookidoo_api import CookidooSearchResult, CookidooShoppingRecipeDetails
from cookidoo_api.types import CookidooCalendarDay

SOURCE = "cookidoo"
CUSTOM_SOURCE = "cookidoo-custom"


class CookidooClient(Protocol):
    async def search_recipes(
        self,
        query: str | None = None,
        *,
        locale: str | None = None,
        languages: str | list[str] | None = None,
        countries: str | list[str] | None = None,
        exclude_ingredients: str | list[str] | None = None,
        total_time: int | None = None,
        page_size: int | None = None,
    ) -> CookidooSearchResult: ...

    async def get_recipe_details(self, id: str) -> CookidooShoppingRecipeDetails: ...

    async def get_recipes_in_calendar_week(
        self, day: date, *, resolve_custom_recipes: bool = False
    ) -> list[CookidooCalendarDay]: ...

    async def add_recipes_to_calendar(
        self, day: date, recipe_ids: list[str]
    ) -> CookidooCalendarDay: ...

    async def remove_recipe_from_calendar(
        self, day: date, recipe_id: str
    ) -> CookidooCalendarDay: ...

    async def add_custom_recipes_to_calendar(
        self, day: date, recipe_ids: list[str]
    ) -> CookidooCalendarDay: ...

    async def remove_custom_recipe_from_calendar(
        self, day: date, recipe_id: str
    ) -> CookidooCalendarDay: ...
