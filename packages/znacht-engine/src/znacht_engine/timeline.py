"""The rolling timeline: My Week is the truth, runs are proposals (ADR-0011).

Pure helpers live here so the day-state model and the coverage heuristic can be tested without
adapters. ``ZnachtService.timeline`` does the reading and calls into these.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from datetime import date, timedelta
from typing import Any, Literal

from znacht.domain.plan import Meal, MealSlot, Week
from znacht.domain.recipe import Recipe, Tag
from znacht.services.pipeline import WeekResult

DayState = Literal["past", "planned", "proposed", "empty"]
Coverage = Literal["arriving", "online_list", "store_run", "none"]

DEFAULT_DAYS = 14
MAX_DAYS = 56
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
COVERAGE_LABEL: dict[str, str] = {
    "online_list": "online list",
    "store_run": "store run",
    "none": "none",
}


def dinner_on(meals: Iterable[Meal], day: date) -> Meal | None:
    """The first dinner on ``day`` in a run's plan (runs plan one dinner per day)."""
    for m in meals:
        if m.date == day and m.slot == MealSlot.DINNER:
            return m
    return None


# Cookidoo's calendar has no meal slots: everything in My Week arrives as a dinner. Breakfasts
# are told apart by tag (Cookidoo categories) or by title.
_BREAKFAST_WORDS = re.compile(
    r"(müsli|muesli|musli|porridge|granola|bircher|overnight oats|frühstück|zmorge|breakfast|brunch"
    r"|smoothie)",
    re.IGNORECASE,
)


def is_breakfast(meal: Meal, recipe: Recipe | None) -> bool:
    if meal.slot == MealSlot.BREAKFAST:
        return True
    if recipe is None:
        return bool(_BREAKFAST_WORDS.search(meal.recipe_id.external_id))
    return Tag.BREAKFAST in recipe.tags or bool(_BREAKFAST_WORDS.search(recipe.title))


def pick_dinner(
    meals: Sequence[Meal], recipe_of: Callable[[Meal], Recipe | None]
) -> tuple[Meal | None, list[Meal]]:
    """(the day's dinner, the rest of the day's recipes). The dinner is the first recipe that is
    not a breakfast; a day with only breakfasts has no dinner."""
    dinner = next((m for m in meals if not is_breakfast(m, recipe_of(m))), None)
    return dinner, [m for m in meals if m is not dinner]


def week_label(week: Week, today: date) -> str:
    this = Week.containing(today)
    if week == this:
        return "This week"
    if week.start == this.start + timedelta(days=7):
        return "Next week"
    return f"Week of {week.start.day} {week.start:%B}"


def span(days: Sequence[date]) -> str:
    """Consecutive days compressed to weekday ranges: Mon–Thu, Sat."""
    out: list[str] = []
    run: list[date] = []
    for d in sorted(days):
        if run and (d - run[-1]).days != 1:
            out.append(_range(run))
            run = []
        run.append(d)
    if run:
        out.append(_range(run))
    return ", ".join(out)


def _range(run: list[date]) -> str:
    first, last = WEEKDAYS[run[0].weekday()], WEEKDAYS[run[-1].weekday()]
    return first if len(run) == 1 else f"{first}–{last}"


def slot_label(result: WeekResult) -> str | None:
    slot = result.shopping.slot
    return f"{WEEKDAYS[slot.start.weekday()]} {slot.start:%H:%M}" if slot else None


def coverage(
    day: date,
    *,
    applied: WeekResult | None,
    from_applied: bool,
    proposal: WeekResult | None,
    list_members: dict[str, frozenset[str]],
) -> dict[str, Any]:
    """The groceries badge for one day. First version of the heuristic (ADR-0011):

    1. a dinner from an applied run is covered by that run's lists: with a delivery slot, days
       after the delivery day are ``arriving <slot>`` and days up to it are a ``store_run`` (the
       split rule puts anything needed on or before the delivery day in store); without a slot
       everything is a store run;
    2. a proposed dinner is ``online_list`` / ``store_run`` when the run's products for that day
       are already on the store's lists (listed, not ordered), else ``none``;
    3. a hand-made dinner is ``none``: nothing links it to a list yet.

    Orders read from the store (roadmap P0-3) replace step 1's "arriving" with a fact; needs
    explosion per day refines steps 2 and 3.
    """
    if from_applied and applied is not None:
        s = applied.shopping
        if s.slot is not None and day > s.slot.delivery_day:
            return {
                "coverage": "arriving",
                "label": f"arriving {slot_label(applied)}",
                "slot": s.slot.start.isoformat(),
                "run_id": None,
            }
        if s.in_store:
            return {"coverage": "store_run", "label": "store run", "slot": None, "run_id": None}
        if s.online:
            return {"coverage": "online_list", "label": "online list", "slot": None, "run_id": None}
        return _none()
    if proposal is not None:
        todays = {
            str(c.product.id)
            for c in (*proposal.shopping.online, *proposal.shopping.in_store)
            if c.needed_on == day
        }
        if todays & list_members.get("online", frozenset()):
            return {"coverage": "online_list", "label": "online list", "slot": None, "run_id": None}
        if todays & list_members.get("in_store", frozenset()):
            return {"coverage": "store_run", "label": "store run", "slot": None, "run_id": None}
    return _none()


def _none() -> dict[str, Any]:
    return {"coverage": "none", "label": "none", "slot": None, "run_id": None}


def summary(days: Sequence[dict[str, Any]], *, awaiting_run_id: int | None) -> str:
    """One line per week: "5 of 7 planned · online order Mon 19:00 covers Tue–Thu ·
    store run Mon · Fri–Sun no groceries"."""
    dated = [(date.fromisoformat(d["date"]), d) for d in days]
    with_dinner = [d for d, r in dated if r["dinner"] is not None]
    proposed = [d for d, r in dated if r["state"] == "proposed"]
    empty = [d for d, r in dated if r["state"] == "empty"]
    parts = [f"{len(with_dinner)} of {len(dated)} planned"]
    if proposed:
        parts.append(
            f"{len(proposed)} proposed"
            + (f" (run {awaiting_run_id} awaits approval)" if awaiting_run_id else "")
        )
    arriving: dict[str, list[date]] = {}
    store: list[date] = []
    listed: list[date] = []
    missing: list[date] = []
    for d, r in dated:
        if r["dinner"] is None and r["state"] != "proposed":
            continue
        g = r["groceries"]
        if g["coverage"] == "arriving":
            arriving.setdefault(g["label"].removeprefix("arriving "), []).append(d)
        elif g["coverage"] == "store_run":
            store.append(d)
        elif g["coverage"] == "online_list":
            listed.append(d)
        else:
            missing.append(d)
    for label, ds in arriving.items():
        parts.append(f"online order {label} covers {span(ds)}")
    if store:
        parts.append(f"store run {span(store)}")
    if listed:
        parts.append(f"online list {span(listed)}")
    if missing:
        parts.append(f"{span(missing)} no groceries")
    if empty:
        parts.append(f"{span(empty)} nothing yet")
    return " · ".join(parts)
