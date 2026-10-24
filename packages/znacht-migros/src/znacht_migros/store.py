"""Migros Online as a Znacht ``GroceryStore``. Lists by explicit ID; ``apply_list`` is the
only method that writes; there is no checkout, order or payment path."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

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
from znacht.domain.recipe import Category
from znacht_migros.mapping import STORE, availability_flag, product_from
from znacht_migros.session import MigrosSession

FREE_TEXT_TYPE = "FREE_TEXT"  # unverified against the live API; see README
_BAD_AVAILABILITY = ("INSUFFICIENT", "OUT_OF", "UNAVAILABLE", "NOT_", "DISCONTINUED")


def _kind(name: str) -> str:
    lowered = name.lower()
    if "online" in lowered or "delivery" in lowered or "liefer" in lowered:
        return "online"
    if "person" in lowered or "store" in lowered or "laden" in lowered or "filiale" in lowered:
        return "in_store"
    return "other"


class MigrosGroceryStore:
    name = STORE

    def __init__(
        self,
        session: MigrosSession,
        *,
        minimum_order: Money | None = None,
        learned_availability: Mapping[str, str] | None = None,
        on_learned: Callable[[dict[str, str]], None] | None = None,
    ) -> None:
        self._s = session
        self._minimum = minimum_order or Money.chf(session.settings.minimum_order)
        self._learned: dict[str, str] = dict(learned_availability or {})
        self._on_learned = on_learned
        self._flags: dict[str, str] = {}  # product-level availability flag per product id
        self._cache: dict[str, Product] = {}

    # -- catalogue (guest token) ------------------------------------------------------
    async def _ids(self, query: str, limit: int) -> list[str]:
        body = {
            "regionId": "national",
            "language": self._s.settings.language,
            "productIds": [],
            "query": query,
            "sortFields": [],
            "sortOrder": "asc",
            "algorithm": "DEFAULT",
        }
        r = await self._s.anonymous("POST", "/onesearch-oc-seaapi/public/v5/search", json=body)
        if r.status_code != 200:
            raise RuntimeError(f"Migros search failed: {r.status_code}")
        return [str(i) for i in (r.json().get("productIds") or [])[:limit]]

    async def _details(self, ids: Sequence[str]) -> dict[str, Product]:
        if not ids:
            return {}
        channels: dict[str, dict[str, Any]] = {}
        for store_type in ("ONLINE", "OFFLINE"):
            r = await self._s.anonymous(
                "GET",
                "/product-display/public/v2/product-detail",
                params={
                    "uids": ",".join(ids),
                    "warehouseId": 1,
                    "storeType": store_type,
                    "region": "national",
                },
            )
            if r.status_code != 200:
                continue
            for item in r.json() or []:
                channels.setdefault(str(item.get("uid")), {})[store_type] = item
        out: dict[str, Product] = {}
        for pid, by_channel in channels.items():
            product = product_from(by_channel.get("ONLINE"), by_channel.get("OFFLINE"))
            flag = availability_flag(by_channel.get("ONLINE") or by_channel.get("OFFLINE") or {})
            if flag:
                self._flags[pid] = flag
            out[pid] = product
            self._cache[pid] = product
        return out

    async def search(
        self, query: str, *, category: Category | None = None, limit: int = 6
    ) -> Sequence[Product]:
        ids = await self._ids(query, max(limit, 1) * 2)
        products = await self._details(ids)
        ordered = [products[i] for i in ids if i in products]
        if category is not None:
            matching = [p for p in ordered if p.category == category]
            others = [p for p in ordered if p.category != category]
            ordered = matching + others
        return ordered[:limit]

    async def product(self, product_id: ProductId) -> Product:
        found = await self._details([str(product_id)])
        if str(product_id) not in found:
            raise LookupError(f"Migros product {product_id} not found")
        return found[str(product_id)]

    # -- delivery ---------------------------------------------------------------------
    async def deliverability(
        self, product_ids: Sequence[ProductId], postcode: str
    ) -> Mapping[ProductId, Deliverability]:
        """Product-level flag first, then what list reads taught us for this address.
        Unknown products are assumed deliverable; the list read after apply corrects that."""
        out: dict[ProductId, Deliverability] = {}
        for pid in product_ids:
            key = str(pid)
            learned = self._learned.get(key)
            flag = self._flags.get(key)
            if learned and any(bad in learned for bad in _BAD_AVAILABILITY):
                out[pid] = Deliverability(
                    product_id=pid, deliverable=False, reason=f"Migros list feedback: {learned}"
                )
            elif flag and "ONLINE" not in flag:
                out[pid] = Deliverability(
                    product_id=pid, deliverable=False, reason=f"Migros availability: {flag}"
                )
            else:
                out[pid] = Deliverability(product_id=pid, deliverable=True)
        return out

    async def delivery_slots(self, postcode: str) -> Sequence[DeliverySlot]:
        """Not known yet (see README); the household's slot templates are used instead."""
        return []

    async def minimum_order(self) -> Money:
        return self._minimum

    async def stock(self, product_ids: Sequence[ProductId]) -> Mapping[ProductId, StockStatus]:
        out: dict[ProductId, StockStatus] = {}
        for pid in product_ids:
            learned = self._learned.get(str(pid))
            if learned is None:
                out[pid] = StockStatus.UNKNOWN
            elif any(bad in learned for bad in _BAD_AVAILABILITY):
                out[pid] = StockStatus.OUT
            else:
                out[pid] = StockStatus.IN_STOCK
        return out

    # -- lists (account JWT) ------------------------------------------------------------
    async def lists(self) -> Sequence[ShoppingListRef]:
        r = await self._s.api("GET", "/shopping-list/public/v1/lists/overview")
        if r.status_code != 200:
            raise RuntimeError(f"Migros lists overview failed: {r.status_code}")
        return [
            ShoppingListRef(
                id=str(x["shoppingListId"]),
                name=str(x.get("shoppingListName") or ""),
                kind=_kind(str(x.get("shoppingListName") or "")),
            )
            for x in r.json()
        ]

    def _learn(self, data: Mapping[str, Any]) -> list[ShoppingListLine]:
        lines: list[ShoppingListLine] = []
        learned_now: dict[str, str] = {}
        for cat in data.get("categories") or []:
            for item in cat.get("items") or []:
                availability = item.get("ecomProductAvailability")
                if item.get("type") == "PRODUCT":
                    pid = str(item["id"])
                    if availability:
                        learned_now[pid] = str(availability)
                    lines.append(
                        ShoppingListLine(
                            product_id=ProductId(pid),
                            quantity=int(item.get("quantity") or 1),
                            availability=availability,
                        )
                    )
                else:
                    lines.append(
                        ShoppingListLine(
                            text=str(item.get("name") or item.get("note") or item.get("id")),
                            quantity=int(item.get("quantity") or 1),
                        )
                    )
        if learned_now:
            self._learned.update(learned_now)
            if self._on_learned:
                self._on_learned(dict(self._learned))
        return lines

    async def read_list(self, list_id: str) -> ShoppingList:
        r = await self._s.api(
            "GET", "/shopping-list/public/v2/list/details", params={"shoppingListId": list_id}
        )
        if r.status_code == 404:
            raise LookupError(f"Migros list {list_id} not found")
        if r.status_code != 200:
            raise RuntimeError(f"Migros list details failed: {r.status_code}")
        return ShoppingList(id=list_id, lines=tuple(self._learn(r.json())))

    async def diff_list(self, list_id: str, target: ShoppingList) -> ListDiff:
        return diff_lists(await self.read_list(list_id), target)

    async def apply_list(self, list_id: str, diff: ListDiff) -> ApplyResult:
        """One batched PUT of target quantities; quantity 0 removes. The only write."""
        items: list[dict[str, Any]] = []
        for change in diff.lines:
            quantity = 0 if change.op == "remove" else change.line.quantity
            if change.line.product_id is not None:
                items.append(
                    {"id": str(change.line.product_id), "quantity": quantity, "type": "PRODUCT"}
                )
            else:
                items.append(
                    {
                        "id": change.line.text,
                        "name": change.line.text,
                        "quantity": quantity,
                        "type": FREE_TEXT_TYPE,
                    }
                )
        if not items:
            return ApplyResult(ok=True, message="nothing to change", applied=0)
        r = await self._s.api(
            "PUT",
            "/shopping-list/public/v3/items",
            json={"shoppingListId": int(list_id), "items": items},
        )
        if r.status_code != 200:
            return ApplyResult(
                ok=False, message=f"Migros rejected the list update: {r.status_code} {r.text[:120]}"
            )
        self._learn(r.json())
        return ApplyResult(ok=True, message=f"{len(items)} changes", applied=len(items))

    def learned_availability(self) -> dict[str, str]:
        return dict(self._learned)
