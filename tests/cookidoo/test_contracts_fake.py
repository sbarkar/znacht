"""The Cookidoo adapters pass the port contract suites against a stateful fake client."""

from datetime import date

import pytest

from tests.cookidoo.fake_client import FakeCookidoo
from znacht.domain.plan import Meal, MealPlan, MealSlot, Week
from znacht.domain.recipe import RecipeId
from znacht.testing.contracts import MealPlanSinkContract, RecipeSourceContract
from znacht_cookidoo import CookidooMealPlanSink, CookidooRecipeSource


class TestCookidooRecipeSourceOnFake(RecipeSourceContract):
    @pytest.fixture
    def source(self):
        return CookidooRecipeSource(FakeCookidoo(), locale="en")

    @pytest.fixture
    def known_recipe_id(self, source):
        return RecipeId(source="cookidoo", external_id="r1002")


class TestCookidooMealPlanSinkOnFake(MealPlanSinkContract):
    @pytest.fixture
    def sink(self):
        return CookidooMealPlanSink(FakeCookidoo(), default_servings=3)

    @pytest.fixture
    def sample_recipe_id(self):
        return RecipeId(source="cookidoo", external_id="r1001")


async def test_apply_groups_adds_per_day_and_handles_custom_recipes():
    fake = FakeCookidoo()
    sink = CookidooMealPlanSink(fake)
    week = Week(start=date(2026, 10, 26))
    fake.calendar[week.start] = [("r1004", False), ("custom-7", True)]
    plan = MealPlan(
        week=week,
        meals=(
            Meal(
                date=week.start,
                slot=MealSlot.DINNER,
                recipe_id=RecipeId(source="cookidoo", external_id="r1001"),
                servings=3,
            ),
            Meal(
                date=week.start,
                slot=MealSlot.LUNCH,
                recipe_id=RecipeId(source="cookidoo", external_id="r1002"),
                servings=3,
            ),
            Meal(
                date=week.end,
                slot=MealSlot.DINNER,
                recipe_id=RecipeId(source="cookidoo-custom", external_id="custom-9"),
                servings=3,
            ),
        ),
    )
    diff = await sink.diff(plan)
    assert {m.recipe_id.external_id for m in diff.add} == {"r1001", "r1002", "custom-9"}
    assert {m.recipe_id.external_id for m in diff.remove} == {"r1004", "custom-7"}
    result = await sink.apply(diff)
    assert result.ok
    assert fake.calls[-4:] == [
        f"remove:{week.start}:r1004",
        f"remove-custom:{week.start}:custom-7",
        f"add:{week.start}:r1001,r1002",
        f"add-custom:{week.end}:custom-9",
    ]
    assert (await sink.diff(plan)).is_empty


async def test_search_fans_out_across_locales_and_merges_by_id():
    from znacht.ports.recipes import RecipeQuery

    fake = FakeCookidoo()
    source = CookidooRecipeSource(fake, locale="en")
    hits = await source.search(RecipeQuery(text="salmon", locales=("en", "de"), limit=10))
    assert [h.id.external_id for h in hits] == ["r1001"]
    assert fake.calls[:2] == ["search:en:salmon", "search:de:salmon"]


async def test_get_refuses_foreign_ids_with_lookup_error():
    source = CookidooRecipeSource(FakeCookidoo())
    with pytest.raises(LookupError):
        await source.get(RecipeId(source="memory", external_id="x"))
