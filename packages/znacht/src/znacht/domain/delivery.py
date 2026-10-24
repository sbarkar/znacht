from __future__ import annotations

from datetime import date, datetime

from pydantic import model_validator

from znacht.domain._base import Frozen
from znacht.domain.money import Money


class DeliverySlot(Frozen):
    id: str
    start: datetime
    end: datetime
    cutoff: datetime | None = None
    price: Money | None = None

    @model_validator(mode="after")
    def _ordered(self) -> DeliverySlot:
        if self.end <= self.start:
            raise ValueError("slot end must be after start")
        return self

    @property
    def delivery_day(self) -> date:
        """The day the groceries are usable. A slot ending at 21:00 still counts as that day:
        anything needed on or before it goes to the in-store list."""
        return self.end.date()
