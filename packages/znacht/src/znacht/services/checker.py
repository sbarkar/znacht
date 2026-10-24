"""The deterministic constraint checker. The LLM proposes; this validates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from znacht.domain.household import Household
from znacht.domain.plan import MealPlan
from znacht.domain.recipe import Recipe, Spiciness
from znacht.domain.violations import Violation


def check_plan(
    plan: MealPlan, recipes: Mapping[str, Recipe], household: Household
) -> list[Violation]:
    rules = household.rules
    out: list[Violation] = []
    dinners = plan.dinners()

    if len(dinners) != rules.dinners_per_week:
        out.append(
            Violation(
                code="dinner_count",
                message=f"{len(dinners)} dinners planned, rules want {rules.dinners_per_week}",
            )
        )

    tag_counts: Counter[str] = Counter()
    repeat_counts: Counter[str] = Counter()
    for meal in plan.meals:
        recipe = recipes.get(meal.recipe_id.key)
        if recipe is None:
            out.append(
                Violation(
                    code="unknown_recipe",
                    message=f"recipe {meal.recipe_id} is not known",
                    date=meal.date,
                    recipe_id=meal.recipe_id,
                )
            )
            continue
        if meal in dinners:
            tag_counts.update(recipe.tags)
        repeat_counts[recipe.id.key] += 1

        for banned in sorted(rules.banned_ingredients):
            if recipe.contains(banned):
                out.append(
                    Violation(
                        code="banned_ingredient",
                        message=f"{recipe.title} contains {banned}",
                        date=meal.date,
                        recipe_id=recipe.id,
                    )
                )
        for allergen in sorted(household.allergies):
            if recipe.contains(allergen):
                out.append(
                    Violation(
                        code="allergen",
                        message=f"{recipe.title} contains allergen {allergen}",
                        date=meal.date,
                        recipe_id=recipe.id,
                    )
                )
        for disliked in sorted(household.dislikes):
            if recipe.contains(disliked):
                out.append(
                    Violation(
                        code="dislike",
                        message=f"{recipe.title} contains {disliked}, which someone dislikes",
                        date=meal.date,
                        recipe_id=recipe.id,
                    )
                )
        if household.needs_mild_food and recipe.spiciness == Spiciness.HOT:
            out.append(
                Violation(
                    code="not_mild",
                    message=f"{recipe.title} is hot; a member needs mild food",
                    date=meal.date,
                    recipe_id=recipe.id,
                )
            )
        if (
            rules.max_total_minutes_weekday is not None
            and meal.date.weekday() < 5
            and recipe.total_minutes is not None
            and recipe.total_minutes > rules.max_total_minutes_weekday
        ):
            out.append(
                Violation(
                    code="too_long_weekday",
                    message=(
                        f"{recipe.title} takes {recipe.total_minutes} min, "
                        f"weekday limit is {rules.max_total_minutes_weekday}"
                    ),
                    date=meal.date,
                    recipe_id=recipe.id,
                )
            )

    for tag, minimum in rules.min_tags.items():
        if tag_counts[tag] < minimum:
            out.append(
                Violation(
                    code="min_tag",
                    message=f"{tag}: {tag_counts[tag]} dinners, need at least {minimum}",
                )
            )
    for tag, maximum in rules.max_tags.items():
        if tag_counts[tag] > maximum:
            out.append(
                Violation(
                    code="max_tag",
                    message=f"{tag}: {tag_counts[tag]} dinners, at most {maximum} allowed",
                )
            )
    for key, count in repeat_counts.items():
        if count > rules.max_repeats_per_week:
            out.append(Violation(code="repeat", message=f"{key} appears {count} times this week"))
    return out
