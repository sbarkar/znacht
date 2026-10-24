from __future__ import annotations

import datetime as dt
from datetime import date, timedelta
from enum import StrEnum

from pydantic import field_validator

from znacht.domain._base import Frozen
from znacht.domain.recipe import RecipeId


class Week(Frozen):
    """A Monday-to-Sunday week."""

    start: date

    @field_validator("start")
    @classmethod
    def _monday(cls, value: date) -> date:
        if value.weekday() != 0:
            raise ValueError(f"week must start on a Monday, got {value} ({value:%A})")
        return value

    @classmethod
    def containing(cls, day: date) -> Week:
        return cls(start=day - timedelta(days=day.weekday()))

    @property
    def end(self) -> date:
        return self.start + timedelta(days=6)

    def days(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(7)]

    def __contains__(self, day: object) -> bool:
        return isinstance(day, date) and self.start <= day <= self.end

    def __str__(self) -> str:
        return f"week of {self.start:%Y-%m-%d}"


class MealSlot(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"


class Meal(Frozen):
    date: dt.date
    slot: MealSlot
    recipe_id: RecipeId
    servings: int
    note: str | None = None

    @field_validator("servings")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("servings must be positive")
        return value


class MealPlan(Frozen):
    week: Week
    meals: tuple[Meal, ...] = ()

    @field_validator("meals")
    @classmethod
    def _sorted(cls, value: tuple[Meal, ...]) -> tuple[Meal, ...]:
        return tuple(sorted(value, key=lambda m: (m.date, list(MealSlot).index(m.slot))))

    def dinners(self) -> list[Meal]:
        return [m for m in self.meals if m.slot == MealSlot.DINNER]

    def on(self, day: date) -> list[Meal]:
        return [m for m in self.meals if m.date == day]

    def recipe_ids(self) -> list[RecipeId]:
        return [m.recipe_id for m in self.meals]
