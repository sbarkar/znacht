"""Prompt text and payload builders. Providers only transport these."""

from __future__ import annotations

import json
from typing import Any

from znacht.domain.household import Household
from znacht.domain.recipe import Recipe
from znacht.ports.planner import PlanningContext

PLANNER_SYSTEM = """You plan a household's dinners for one week, Monday to Sunday.

You are a thoughtful home cook, not a nutritionist with a clipboard. Make the week feel
like a week: a rhythm of light and hearty, quick weekday dinners and one or two that are
worth the weekend, ingredients that carry over so nothing wilts in the fridge.

Hard rules, which a deterministic checker enforces after you answer:
- Use only recipe_ids from the candidates list, exactly as written.
- Respect the weekly counts (minimums and maximums) and the banned ingredients.
- Never pick a hot or spicy recipe when someone needs mild food (a toddler, say).
- Respect allergies absolutely; treat dislikes as hard too.
- Weekday dinners must fit the weekday time limit when one is given.
- Do not repeat a recipe within the week.
- Every dinner gets the household's servings.

Soft preferences: family-friendly first; ratings are a guide, not a filter; share
ingredients across dinners; vary proteins and cuisines; put the longest recipe on the
weekend. If a previous attempt had violations, fix exactly those.

Answer only in the structured format you are given."""

EXTRACT_LAB_SYSTEM = """You read a medical laboratory report and transcribe its markers faithfully.
Copy values and units exactly as printed. Do not interpret, do not round, do not invent a
marker that is not on the page. Flag only what the lab itself flagged. The household will
confirm every line before it is used."""

EXTRACT_PANTRY_SYSTEM = """You look at photos of a kitchen pantry, fridge or shelf and list what is there with
your best estimate of the remaining quantity. Use cook's names in English. Prefer weight or
volume when the packaging shows it; otherwise count pieces. Be honest about confidence and
list what you could not identify under 'unsure'."""


def _candidate(recipe: Recipe) -> dict[str, Any]:
    return {
        "recipe_id": recipe.id.key,
        "title": recipe.title,
        "tags": sorted(recipe.tags),
        "total_minutes": recipe.total_minutes,
        "spiciness": str(recipe.spiciness),
        "rating": recipe.rating,
        "servings": recipe.servings,
        "ingredients": [i.name for i in recipe.ingredients][:14],
    }


def planning_payload(context: PlanningContext) -> str:
    """The user message: household constraints, the week, candidates, and prior violations."""
    h: Household = context.household
    rules = h.rules
    payload: dict[str, Any] = {
        "week": {
            "monday": context.week.start.isoformat(),
            "days": [d.isoformat() for d in context.week.days()],
        },
        "household": {
            "members": [
                {
                    "age_group": str(m.age_group),
                    "needs_mild_food": m.needs_mild_food,
                    "dislikes": sorted(m.dislikes),
                    "allergies": sorted(m.allergies),
                }
                for m in h.members
            ],
            "servings_per_dinner": h.servings,
            "dinners_per_week": rules.dinners_per_week,
            "min_per_week": rules.min_tags,
            "max_per_week": rules.max_tags,
            "banned_ingredients": sorted(rules.banned_ingredients),
            "weekday_max_total_minutes": rules.max_total_minutes_weekday,
            "health_rules": [r.text for r in h.health.rules],
            "pantry": [f"{i.quantity} {i.name}" for i in h.pantry.items],
            "makes_at_home": [m.dish for m in h.make_at_home],
        },
        "candidates": [_candidate(r) for r in context.candidates],
    }
    if context.violations:
        payload["previous_attempt_violations"] = [str(v) for v in context.violations]
    if context.previous is not None and context.previous.meals:
        payload["previous_attempt"] = [
            {"date": m.date.isoformat(), "recipe_id": m.recipe_id.key}
            for m in context.previous.meals
        ]
    return json.dumps(payload, ensure_ascii=False, indent=1, default=str)
