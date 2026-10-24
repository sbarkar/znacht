from __future__ import annotations

from collections import defaultdict
from datetime import date

from znacht.domain.diff import ApplyResult, PlanDiff
from znacht.domain.plan import Meal, MealPlan, MealSlot, Week
from znacht.domain.recipe import RecipeId
from znacht_cookidoo.client import CUSTOM_SOURCE, SOURCE, CookidooClient
from znacht_cookidoo.mapping import day_date, meal_from


class CookidooMealPlanSink:
    """Cookidoo "My Week", which syncs to the Thermomix.

    My Week has days, not meal slots, so a plan's meals are matched by (date, recipe)
    only. Servings are not stored by Cookidoo; reads use ``default_servings``.
    """

    name = SOURCE

    def __init__(self, client: CookidooClient, *, default_servings: int = 4) -> None:
        self._client = client
        self._servings = default_servings

    async def read_week(self, week: Week) -> MealPlan:
        days = await self._client.get_recipes_in_calendar_week(
            week.start, resolve_custom_recipes=True
        )
        meals: list[Meal] = []
        for day in days:
            when = day_date(day)
            if when is None or when not in week:
                continue
            meals.extend(meal_from(when, r, self._servings) for r in day.recipes)
            known = {r.id for r in day.recipes}
            # custom recipes that could not be resolved are still planned: keep them by ID
            for custom_id in day.customer_recipe_ids:
                if custom_id not in known:
                    meals.append(
                        Meal(
                            date=when,
                            slot=MealSlot.DINNER,
                            recipe_id=RecipeId(source=CUSTOM_SOURCE, external_id=custom_id),
                            servings=self._servings,
                        )
                    )
        return MealPlan(week=week, meals=tuple(meals))

    async def diff(self, plan: MealPlan) -> PlanDiff:
        current = await self.read_week(plan.week)
        have = {(m.date, m.recipe_id.key): m for m in current.meals}
        want = {(m.date, m.recipe_id.key): m for m in plan.meals if m.date in plan.week}
        add = tuple(m for k, m in want.items() if k not in have)
        remove = tuple(m for k, m in have.items() if k not in want)
        return PlanDiff(week=plan.week, add=add, remove=remove)

    async def apply(self, diff: PlanDiff) -> ApplyResult:
        """The only method that writes to Cookidoo."""
        applied = 0
        for meal in diff.remove:
            if meal.recipe_id.source == CUSTOM_SOURCE:
                await self._client.remove_custom_recipe_from_calendar(
                    meal.date, meal.recipe_id.external_id
                )
            else:
                await self._client.remove_recipe_from_calendar(
                    meal.date, meal.recipe_id.external_id
                )
            applied += 1
        grouped: dict[tuple[date, bool], list[str]] = defaultdict(list)
        for meal in diff.add:
            grouped[(meal.date, meal.recipe_id.source == CUSTOM_SOURCE)].append(
                meal.recipe_id.external_id
            )
        for (day, custom), ids in sorted(grouped.items()):
            ids = sorted(ids)
            if custom:
                await self._client.add_custom_recipes_to_calendar(day, ids)
            else:
                await self._client.add_recipes_to_calendar(day, ids)
            applied += len(ids)
        return ApplyResult(
            ok=True, message=f"+{len(diff.add)} -{len(diff.remove)}", applied=applied
        )
