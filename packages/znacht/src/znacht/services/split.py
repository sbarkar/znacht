from __future__ import annotations

from znacht.domain.delivery import DeliverySlot
from znacht.domain.needs import IngredientNeed


def timing_split(
    needs: list[IngredientNeed], slot: DeliverySlot | None
) -> tuple[list[IngredientNeed], list[IngredientNeed]]:
    """Split needs into (online candidates, in-store) by when they are needed.

    Anything needed on or before the delivery day goes in-store: a slot that ends at
    21:00 cannot feed that evening's dinner. With no slot, everything is in-store.
    """
    if slot is None:
        return [], list(needs)
    online = [n for n in needs if n.needed_on > slot.delivery_day]
    in_store = [n for n in needs if n.needed_on <= slot.delivery_day]
    return online, in_store
