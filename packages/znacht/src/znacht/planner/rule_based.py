"""A deterministic planner that needs no LLM.

It is the test planner, the fallback when a provider is unreachable, and proof that the
pipeline does not depend on any provider. It is greedy: satisfy the minimum tag counts
first, then fill the week with the best-rated family-friendly candidates, pushing the
longest recipes to the weekend.
"""

from __future__ import annotations

from collections import Counter
from typing import TypeVar

from pydantic import BaseModel

from znacht.domain.household import Household
from znacht.domain.plan import Meal, MealPlan, MealSlot
from znacht.domain.recipe import Recipe, Spiciness, Tag
from znacht.ports.planner import Document, PlanningContext, PlanProposal

T = TypeVar("T", bound=BaseModel)


def _acceptable(recipe: Recipe, household: Household) -> bool:
    rules = household.rules
    blocked = rules.banned_ingredients | household.allergies | household.dislikes
    if any(recipe.contains(name) for name in blocked):
        return False
    return not (household.needs_mild_food and recipe.spiciness == Spiciness.HOT)


def _score(recipe: Recipe) -> float:
    score = recipe.rating if recipe.rating is not None else 3.0
    if recipe.has_tag(Tag.FAMILY):
        score += 0.5
    return score


class RuleBasedPlanner:
    name = "rule_based"

    async def propose(self, context: PlanningContext) -> PlanProposal:
        household = context.household
        rules = household.rules
        pool = sorted(
            (r for r in context.candidates if _acceptable(r, household)),
            key=lambda r: (-_score(r), r.title),
        )
        chosen: list[Recipe] = []
        counts: Counter[str] = Counter()

        def fits(recipe: Recipe) -> bool:
            if recipe in chosen:
                return False
            return all(
                counts[tag] + 1 <= limit
                for tag, limit in rules.max_tags.items()
                if recipe.has_tag(tag)
            )

        def take(recipe: Recipe) -> None:
            chosen.append(recipe)
            counts.update(recipe.tags)

        for tag, minimum in sorted(rules.min_tags.items(), key=lambda kv: -kv[1]):
            for recipe in pool:
                if counts[tag] >= minimum:
                    break
                if recipe.has_tag(tag) and fits(recipe):
                    take(recipe)
        for recipe in pool:
            if len(chosen) >= rules.dinners_per_week:
                break
            if fits(recipe):
                take(recipe)

        days = context.week.days()[: rules.dinners_per_week]
        weekend = [d for d in days if d.weekday() >= 5]
        weekdays = [d for d in days if d.weekday() < 5]
        by_length = sorted(chosen, key=lambda r: -(r.total_minutes or 0))
        order = weekend + weekdays
        meals = tuple(
            Meal(date=day, slot=MealSlot.DINNER, recipe_id=recipe.id, servings=household.servings)
            for day, recipe in zip(order, by_length, strict=False)
        )
        rationale = (
            f"rule-based: {len(meals)} dinners from {len(pool)} acceptable candidates; "
            f"tags {dict(counts)}"
        )
        return PlanProposal(plan=MealPlan(week=context.week, meals=meals), rationale=rationale)

    async def extract(self, document: Document, schema: type[T]) -> T:
        raise NotImplementedError(
            "the rule-based planner cannot extract documents; use an LLM provider"
        )
