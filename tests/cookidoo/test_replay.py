"""The real cookidoo-api client against recorded, scrubbed HTTP. No network, no secrets."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

import pytest
from aiohttp import ClientSession, CookieJar
from cookidoo_api import Cookidoo, CookidooAuthData, CookidooConfig, CookidooLocalizationConfig

from tests.cookidoo.vcr_config import FUTURE_WEEK, KNOWN_RECIPE_ID, SEARCH_QUERY, cassette
from znacht.domain.plan import Meal, MealPlan, MealSlot, Week
from znacht.domain.recipe import Category, RecipeId
from znacht.ports.recipes import RecipeQuery
from znacht_cookidoo import CookidooMealPlanSink, CookidooRecipeSource

LOCALISATION = CookidooLocalizationConfig(
    country_code="ch", language="en", url="https://cookidoo.ch/foundation/en"
)


@pytest.fixture
async def client() -> AsyncIterator[Cookidoo]:
    with cassette("none"):
        async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as http:
            c = Cookidoo(http, CookidooConfig(localization=LOCALISATION, email="x", password="x"))
            c.apply_auth_data(
                CookidooAuthData(
                    access_token="replay", refresh_token="replay", expires_at=time.time() + 3600
                )
            )
            yield c


async def test_search_replays_recorded_hits(client: Cookidoo):
    source = CookidooRecipeSource(client, locale="en", details=False)
    hits = await source.search(RecipeQuery(text=SEARCH_QUERY, limit=5))
    assert len(hits) == 5
    assert hits[0].id == RecipeId(source="cookidoo", external_id=KNOWN_RECIPE_ID)
    assert all(h.title for h in hits)
    assert all(h.url and h.url.startswith("https://cookidoo.ch/") for h in hits)


async def test_search_passes_exclusions_through(client: Cookidoo):
    source = CookidooRecipeSource(client, locale="en", details=False)
    hits = await source.search(
        RecipeQuery(text=SEARCH_QUERY, exclude_ingredients=frozenset({"cheese"}), limit=5)
    )
    assert len(hits) == 5


async def test_get_maps_a_real_recipe(client: Cookidoo):
    source = CookidooRecipeSource(client, locale="en")
    recipe = await source.get(RecipeId(source="cookidoo", external_id=KNOWN_RECIPE_ID))
    assert recipe.title == "Pasta alla carcerata"
    assert recipe.servings >= 1
    assert recipe.total_minutes and recipe.total_minutes > 0
    assert len(recipe.ingredients) == 10
    assert any(i.category == Category.GRAIN for i in recipe.ingredients)
    assert all(i.quantity.value > 0 for i in recipe.ingredients)
    assert all(i.raw for i in recipe.ingredients)
    assert recipe.tags  # at least one inferred tag
    assert recipe.locale == "en"


async def test_get_unknown_recipe_raises_lookup_error(client: Cookidoo):
    source = CookidooRecipeSource(client, locale="en")
    with pytest.raises(LookupError):
        await source.get(RecipeId(source="cookidoo", external_id="r000000"))


async def test_read_week_and_diff_against_an_empty_week(client: Cookidoo):
    sink = CookidooMealPlanSink(client, default_servings=3)
    week = Week(start=FUTURE_WEEK)
    current = await sink.read_week(week)
    assert current.meals == ()
    plan = MealPlan(
        week=week,
        meals=(
            Meal(
                date=week.start,
                slot=MealSlot.DINNER,
                recipe_id=RecipeId(source="cookidoo", external_id=KNOWN_RECIPE_ID),
                servings=3,
            ),
        ),
    )
    diff = await sink.diff(plan)
    assert len(diff.add) == 1 and diff.remove == ()
