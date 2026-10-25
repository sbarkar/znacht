"""Editing the schedule and locking what was ordered (ADR-0014).

Pure helpers: how an edit changes My Week and the lists, and what an order locks. The reading and
writing live in ``ZnachtService``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any, Literal

from znacht.domain.diff import PlanDiff, ShoppingList, ShoppingListLine
from znacht.domain.plan import Meal, MealSlot
from znacht.services.pipeline import WeekResult

EditKind = Literal["swap", "add", "remove", "move"]
EDIT_KINDS: tuple[str, ...] = ("swap", "add", "remove", "move")


class OrderedLock(PermissionError):
    """A write would change a day whose groceries were ordered."""


class StaleEdit(ValueError):
    """My Week changed between the preview and the confirm (or since a proposal was planned)."""


def touched_dates(diff: PlanDiff | None) -> set[date]:
    if diff is None:
        return set()
    return {m.date for m in (*diff.add, *diff.remove)}


def diff_keys(
    diff: PlanDiff | None,
) -> tuple[frozenset[tuple[date, str]], frozenset[tuple[date, str]]]:
    """A diff by (date, recipe) only: servings and notes do not survive a Cookidoo read."""
    if diff is None:
        return frozenset(), frozenset()
    return (
        frozenset((m.date, m.recipe_id.key) for m in diff.add),
        frozenset((m.date, m.recipe_id.key) for m in diff.remove),
    )


def edit_changes(
    kind: str,
    day: date,
    current: dict[date, Meal | None],
    *,
    new: Meal | None = None,
    to: date | None = None,
) -> tuple[list[Meal], list[Meal]]:
    """(add, remove) for My Week. ``current`` is each touched day's dinner as read just now; only
    those dinners are removed, so breakfasts and other days never enter the diff."""
    here = current.get(day)
    if kind == "swap":
        if new is None:
            raise ValueError("a swap needs a recipe")
        if here is not None and here.recipe_id == new.recipe_id:
            raise ValueError("that is already the dinner on this day")
        return [new], [here] if here is not None else []
    if kind == "add":
        if new is None:
            raise ValueError("pick a recipe to add")
        if here is not None:
            raise ValueError("this day already has a dinner; swap it instead")
        return [new], []
    if kind == "remove":
        if here is None:
            raise ValueError("there is no dinner to remove on this day")
        return [], [here]
    if kind == "move":
        if here is None:
            raise ValueError("there is no dinner to move on this day")
        if to is None or to == day:
            raise ValueError("pick another day to move it to")
        there = current.get(to)
        add = [here.model_copy(update={"date": to})]
        remove = [here]
        if there is not None:  # moving onto a dinner swaps the two days
            add.append(there.model_copy(update={"date": day}))
            remove.append(there)
        return add, remove
    raise ValueError(f"unknown edit {kind!r}; one of {', '.join(EDIT_KINDS)}")


def grocery_meals(
    kind: str,
    base: Sequence[Meal],
    add: Sequence[Meal],
    dates: Iterable[date],
    *,
    moved_from: dict[date, date] | None = None,
) -> tuple[Meal, ...]:
    """The plan an edit's groceries are priced for: the applied run's plan with the edited days
    changed. A swapped or added dinner brings its groceries; a moved dinner keeps them only if the
    applied run bought for it (a hand-made dinner had none, and moving it does not add any)."""
    touched = set(dates)
    base_on = {m.date: m for m in base if m.slot == MealSlot.DINNER}
    kept = [m for m in base if not (m.slot == MealSlot.DINNER and m.date in touched)]
    for meal in add:
        if kind == "move":
            origin = (moved_from or {}).get(meal.date)
            had = base_on.get(origin) if origin is not None else None
            if had is None or had.recipe_id != meal.recipe_id:
                continue
            meal = had.model_copy(update={"date": meal.date})
        kept.append(meal)
    return tuple(kept)


def rebase_list(live: ShoppingList, before: ShoppingList, after: ShoppingList) -> ShoppingList:
    """What the list should hold after an edit: ``live - before + after`` per product, removed at
    zero, so the household's own lines and quantities on untouched products stay as they are.
    Free-text lines are present or not: added when the edit brings them, removed when only the
    edit's base had them."""
    old = {line.key: line for line in before.lines}
    new = {line.key: line for line in after.lines}
    out: list[ShoppingListLine] = []
    seen: set[str] = set()
    for line in live.lines:
        key = line.key
        seen.add(key)
        if line.product_id is None:
            if key in old and key not in new:
                continue
            out.append(line)
            continue
        qty = line.quantity - (old[key].quantity if key in old else 0)
        qty += new[key].quantity if key in new else 0
        if qty > 0:
            out.append(line.model_copy(update={"quantity": qty}))
    for key, line in new.items():
        if key in seen:
            continue
        if line.product_id is None:
            if key not in old:
                out.append(line)
            continue
        qty = line.quantity - (old[key].quantity if key in old else 0)
        if qty > 0:
            out.append(line.model_copy(update={"quantity": qty}))
    return ShoppingList(id=live.id, lines=tuple(out))


def suggested_order_dates(result: WeekResult, today: date) -> list[date]:
    """The days an online order for ``result`` feeds: dinners after the delivery day (the split
    rule puts everything needed up to it in store), else every dinner from today on."""
    dinners = sorted({m.date for m in result.plan.dinners() if m.date >= today})
    slot = result.shopping.slot
    if slot is not None:
        after = [d for d in dinners if d > slot.delivery_day]
        if after:
            return after
    return dinners


def lock_reason(order: dict[str, Any]) -> str:
    placed = datetime.fromisoformat(order["placed_at"]).astimezone()
    who = "read from Migros" if order.get("source") == "migros" else "marked by you"
    return (
        f"Groceries ordered {placed:%a} {placed.day} {placed:%b %H:%M} ({who}). "
        "Znacht leaves this day alone; change it in Cookidoo if you must."
    )
