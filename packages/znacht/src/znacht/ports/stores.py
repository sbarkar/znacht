from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from znacht.domain.delivery import DeliverySlot
from znacht.domain.diff import ApplyResult, ListDiff, ShoppingList, ShoppingListRef
from znacht.domain.money import Money
from znacht.domain.product import Deliverability, Product, ProductId, StockStatus
from znacht.domain.recipe import Category


@runtime_checkable
class GroceryStore(Protocol):
    """A store with a catalogue, delivery, and shopping lists addressed by explicit ID.

    Deliberately absent: checkout, order placement, payment, slot booking.
    ``apply_list`` is the only method that writes.
    """

    name: str

    async def search(
        self, query: str, *, category: Category | None = None, limit: int = 6
    ) -> Sequence[Product]: ...

    async def product(self, product_id: ProductId) -> Product: ...

    async def deliverability(
        self, product_ids: Sequence[ProductId], postcode: str
    ) -> Mapping[ProductId, Deliverability]: ...

    async def delivery_slots(self, postcode: str) -> Sequence[DeliverySlot]: ...

    async def minimum_order(self) -> Money: ...

    async def stock(self, product_ids: Sequence[ProductId]) -> Mapping[ProductId, StockStatus]: ...

    async def lists(self) -> Sequence[ShoppingListRef]: ...

    async def read_list(self, list_id: str) -> ShoppingList: ...

    async def diff_list(self, list_id: str, target: ShoppingList) -> ListDiff: ...

    async def apply_list(self, list_id: str, diff: ListDiff) -> ApplyResult: ...
