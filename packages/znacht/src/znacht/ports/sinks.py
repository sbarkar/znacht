from __future__ import annotations

from typing import Protocol, runtime_checkable

from znacht.domain.diff import ApplyResult, PlanDiff
from znacht.domain.plan import MealPlan, Week


@runtime_checkable
class MealPlanSink(Protocol):
    """Where the household cooks from. ``apply`` is the only method that writes."""

    name: str

    async def read_week(self, week: Week) -> MealPlan: ...

    async def diff(self, plan: MealPlan) -> PlanDiff: ...

    async def apply(self, diff: PlanDiff) -> ApplyResult: ...
