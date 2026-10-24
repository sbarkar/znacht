"""A stateful in-memory stand-in for cookidoo-api, shaped like the client Protocol."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from cookidoo_api import (
    CookidooCategory,
    CookidooException,
    CookidooIngredient,
    CookidooSearchRecipeHit,
    CookidooSearchResult,
    CookidooShoppingRecipeDetails,
)
from cookidoo_api.types import CookidooCalendarDay, CookidooCalendarDayRecipe


def details(
    rid: str,
    name: str,
    ingredients: list[tuple[str, str]],
    *,
    categories: list[str] = (),
    servings: int = 4,
    total_time: int = 1800,
) -> CookidooShoppingRecipeDetails:
    return CookidooShoppingRecipeDetails(
        id=rid,
        name=name,
        ingredients=[
            CookidooIngredient(id=f"{rid}-{i}", name=n, description=d)
            for i, (n, d) in enumerate(ingredients)
        ],
        thumbnail=None,
        image=None,
        url=f"https://cookidoo.ch/recipes/recipe/en/{rid}",
        difficulty="easy",
        notes=[],
        categories=[CookidooCategory(id=c, name=c, notes="") for c in categories],
        collections=[],
        utensils=[],
        serving_size=servings,
        active_time=900,
        total_time=total_time,
        nutrition_groups=[],
        step_groups=[],
    )


CATALOGUE: dict[str, CookidooShoppingRecipeDetails] = {
    d.id: d
    for d in [
        details(
            "r1001",
            "Salmon with lemon potatoes",
            [
                ("salmon fillet", "500 g"),
                ("potatoes", "800 g"),
                ("lemon", "1"),
                ("olive oil", "2 tbsp"),
                ("dill", "1 - 2 sprigs"),
            ],
            categories=["Fish & seafood"],
        ),
        details(
            "r1002",
            "Red lentil dal",
            [
                ("red lentils", "300 g"),
                ("coconut milk", "400 ml"),
                ("onion", "1"),
                ("salt", "1 tsp"),
            ],
            categories=["Vegetarian", "Family favourites"],
        ),
        details(
            "r1003",
            "Spicy beef chilli",
            [("minced beef", "500 g"), ("kidney beans", "2 cans"), ("chilli", "2")],
            categories=["Meat"],
        ),
        details(
            "r1004",
            "Pasta with cheese sauce",
            [("pasta", "400 g"), ("cheese", "150 g"), ("milk", "2.5 dl")],
            categories=["Pasta"],
        ),
    ]
}


class FakeCookidoo:
    def __init__(self) -> None:
        self.calendar: dict[date, list[tuple[str, bool]]] = defaultdict(list)
        self.calls: list[str] = []

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
    ) -> CookidooSearchResult:
        self.calls.append(f"search:{locale}:{query}")
        excluded = {e.lower() for e in (exclude_ingredients or [])}
        hits = [
            CookidooSearchRecipeHit(id=d.id, name=d.name, thumbnail=None, image=None, url=d.url)
            for d in CATALOGUE.values()
            if (not query or query.lower() in d.name.lower())
            and not any(e in i.name.lower() for i in d.ingredients for e in excluded)
            and (total_time is None or d.total_time <= total_time)
        ]
        return CookidooSearchResult(recipes=hits[: page_size or 50], total=len(hits))

    async def get_recipe_details(self, id: str) -> CookidooShoppingRecipeDetails:
        self.calls.append(f"details:{id}")
        if id not in CATALOGUE:
            raise CookidooException(f"recipe {id} not found")
        return CATALOGUE[id]

    def _day(self, day: date) -> CookidooCalendarDay:
        recipes = [
            CookidooCalendarDayRecipe(
                id=rid,
                name=CATALOGUE[rid].name if rid in CATALOGUE else rid,
                total_time=0,
                thumbnail=None,
                image=None,
                url="",
                is_custom=custom,
            )
            for rid, custom in self.calendar.get(day, [])
        ]
        return CookidooCalendarDay(id=day.isoformat(), title=day.isoformat(), recipes=recipes)

    async def get_recipes_in_calendar_week(
        self, day: date, *, resolve_custom_recipes: bool = False
    ) -> list[CookidooCalendarDay]:
        self.calls.append(f"week:{day}")
        start = day
        from datetime import timedelta

        return [self._day(start + timedelta(days=i)) for i in range(7)]

    async def add_recipes_to_calendar(
        self, day: date, recipe_ids: list[str]
    ) -> CookidooCalendarDay:
        self.calls.append(f"add:{day}:{','.join(recipe_ids)}")
        for rid in recipe_ids:
            if (rid, False) not in self.calendar[day]:
                self.calendar[day].append((rid, False))
        return self._day(day)

    async def remove_recipe_from_calendar(self, day: date, recipe_id: str) -> CookidooCalendarDay:
        self.calls.append(f"remove:{day}:{recipe_id}")
        self.calendar[day] = [e for e in self.calendar[day] if e != (recipe_id, False)]
        return self._day(day)

    async def add_custom_recipes_to_calendar(
        self, day: date, recipe_ids: list[str]
    ) -> CookidooCalendarDay:
        self.calls.append(f"add-custom:{day}:{','.join(recipe_ids)}")
        for rid in recipe_ids:
            if (rid, True) not in self.calendar[day]:
                self.calendar[day].append((rid, True))
        return self._day(day)

    async def remove_custom_recipe_from_calendar(
        self, day: date, recipe_id: str
    ) -> CookidooCalendarDay:
        self.calls.append(f"remove-custom:{day}:{recipe_id}")
        self.calendar[day] = [e for e in self.calendar[day] if e != (recipe_id, True)]
        return self._day(day)
