from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from znacht.domain.delivery import DeliverySlot
from znacht.domain.diff import (
    ApplyResult,
    ListDiff,
    ShoppingList,
    ShoppingListLine,
    ShoppingListRef,
    diff_lists,
)
from znacht.domain.money import Money
from znacht.domain.product import Deliverability, Product, ProductId, StockStatus
from znacht.domain.recipe import Category, normalise_name

DEFAULT_MINIMUM_ORDER = Money.chf(99)


class MemoryGroceryStore:
    """A fixture store. Deliverability is per product *and* postcode; stock per product.

    There is no checkout, order or payment method, and there never will be.
    """

    name = "memory"

    def __init__(
        self,
        products: Iterable[Product],
        *,
        lists: Iterable[ShoppingListRef] = (),
        slots: Mapping[str, Sequence[DeliverySlot]] | None = None,
        minimum_order: Money = DEFAULT_MINIMUM_ORDER,
        non_deliverable: Mapping[str, Iterable[ProductId]] | None = None,
        stock: Mapping[ProductId, StockStatus] | None = None,
        search_terms: Mapping[ProductId, Iterable[str]] | None = None,
    ) -> None:
        self._products = {p.id: p for p in products}
        self._lists: dict[str, ShoppingList] = {ref.id: ShoppingList(id=ref.id) for ref in lists}
        self._refs = list(lists)
        self._slots = dict(slots or {})
        self._minimum = minimum_order
        self._non_deliverable = {pc: frozenset(ids) for pc, ids in (non_deliverable or {}).items()}
        self._stock = dict(stock or {})
        self._terms = {
            pid: [normalise_name(t) for t in terms] for pid, terms in (search_terms or {}).items()
        }
        self.applied: list[ListDiff] = []

    async def search(
        self, query: str, *, category: Category | None = None, limit: int = 6
    ) -> Sequence[Product]:
        q = normalise_name(query)
        hits = [
            p
            for p in self._products.values()
            if (q in normalise_name(p.name) or q in self._terms.get(p.id, []))
            and (category is None or p.category == category)
        ]
        hits.sort(key=lambda p: (p.name, p.id))
        return hits[:limit]

    async def product(self, product_id: ProductId) -> Product:
        try:
            return self._products[product_id]
        except KeyError as exc:
            raise LookupError(f"unknown product {product_id}") from exc

    async def deliverability(
        self, product_ids: Sequence[ProductId], postcode: str
    ) -> Mapping[ProductId, Deliverability]:
        blocked = self._non_deliverable.get(postcode, frozenset())
        return {
            pid: Deliverability(
                product_id=pid,
                deliverable=pid not in blocked,
                reason="not deliverable to this postcode" if pid in blocked else None,
            )
            for pid in product_ids
        }

    async def delivery_slots(self, postcode: str) -> Sequence[DeliverySlot]:
        return list(self._slots.get(postcode, ()))

    async def minimum_order(self) -> Money:
        return self._minimum

    async def stock(self, product_ids: Sequence[ProductId]) -> Mapping[ProductId, StockStatus]:
        return {pid: self._stock.get(pid, StockStatus.IN_STOCK) for pid in product_ids}

    async def lists(self) -> Sequence[ShoppingListRef]:
        return list(self._refs)

    async def read_list(self, list_id: str) -> ShoppingList:
        try:
            return self._lists[list_id]
        except KeyError as exc:
            raise LookupError(f"unknown list {list_id}") from exc

    async def diff_list(self, list_id: str, target: ShoppingList) -> ListDiff:
        return diff_lists(await self.read_list(list_id), target)

    async def apply_list(self, list_id: str, diff: ListDiff) -> ApplyResult:
        current = dict((await self.read_list(list_id)).as_dict())
        for change in diff.lines:
            if change.op == "remove":
                current.pop(change.line.key, None)
            else:
                current[change.line.key] = change.line
        self._lists[list_id] = ShoppingList(id=list_id, lines=tuple(current.values()))
        self.applied.append(diff)
        return ApplyResult(ok=True, message=f"{len(diff.lines)} changes", applied=len(diff.lines))

    def set_stock(self, product_id: ProductId, status: StockStatus) -> None:
        self._stock[product_id] = status

    def seed_list(self, list_id: str, lines: Iterable[ShoppingListLine]) -> None:
        self._lists[list_id] = ShoppingList(id=list_id, lines=tuple(lines))
