from __future__ import annotations

from znacht.domain.diff import ApplyResult, PlanDiff
from znacht.domain.plan import Meal, MealPlan, Week


class MemoryMealPlanSink:
    """Holds meals per week. ``apply`` is the only method that mutates it."""

    name = "memory"

    def __init__(self) -> None:
        self.meals: set[Meal] = set()
        self.applied: list[PlanDiff] = []

    async def read_week(self, week: Week) -> MealPlan:
        return MealPlan(week=week, meals=tuple(m for m in self.meals if m.date in week))

    async def diff(self, plan: MealPlan) -> PlanDiff:
        current = set((await self.read_week(plan.week)).meals)
        target = set(plan.meals)
        return PlanDiff(
            week=plan.week,
            add=tuple(sorted(target - current, key=lambda m: (m.date, m.slot))),
            remove=tuple(sorted(current - target, key=lambda m: (m.date, m.slot))),
        )

    async def apply(self, diff: PlanDiff) -> ApplyResult:
        for meal in diff.remove:
            self.meals.discard(meal)
        for meal in diff.add:
            self.meals.add(meal)
        self.applied.append(diff)
        return ApplyResult(
            ok=True,
            message=f"+{len(diff.add)} -{len(diff.remove)}",
            applied=len(diff.add) + len(diff.remove),
        )
