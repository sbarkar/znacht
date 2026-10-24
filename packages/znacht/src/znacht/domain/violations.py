from __future__ import annotations

import datetime as dt

from znacht.domain._base import Frozen
from znacht.domain.recipe import RecipeId


class Violation(Frozen):
    code: str
    message: str
    date: dt.date | None = None
    recipe_id: RecipeId | None = None

    def __str__(self) -> str:
        where = f" ({self.date})" if self.date else ""
        return f"[{self.code}] {self.message}{where}"
