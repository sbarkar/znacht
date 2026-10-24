"""A respx mock of the Migros endpoints the adapter uses, with list state.

Shapes copied from live responses on 2026-10-24 (see docs/decisions/0008).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import respx

WWW = "https://www.migros.ch"


def detail(
    uid: int,
    name: str,
    crumbs: list[str],
    *,
    online: tuple[str, str, str] | None,  # (advertised, effective, pack)
    store: tuple[str, str, str] | None,
    availability: str = "ONLINE_AND_INSTORE",
    brand: str = "Migros",
    nutrients: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    def offer(kind: tuple[str, str, str], channel: dict[str, Any]) -> dict[str, Any]:
        adv, eff, pack = kind
        return {
            "channel": channel,
            "price": {
                "advertisedValue": float(adv),
                "effectiveValue": float(eff),
                "unitPrice": {"unit": "100g", "value": 0.1},
            },
            "quantity": pack,
            "type": "STANDARD" if adv == eff else "PROMOTION",
            "isNotMorningDeliverable": False,
            "maxOrderableQuantityV2": 96,
        }

    base: dict[str, Any] = {
        "uid": uid,
        "name": name,
        "title": f"{brand} · {name}",
        "brand": brand,
        "migrosId": str(uid) + "000",
        "breadcrumb": [{"id": str(i), "name": c} for i, c in enumerate(crumbs)],
        "productAvailability": availability,
        "productUrls": f"{WWW}/en/product/{uid}",
        "productInformation": {
            "mainInformation": {"brand": {"name": brand}},
            **(
                {
                    "nutrientsInformation": {
                        "nutrientsTableV2": {
                            "headers": [{"value": "100 g"}],
                            "rows": [{"label": k, "values": [v]} for k, v in nutrients.items()],
                        }
                    }
                }
                if nutrients
                else {}
            ),
        },
    }
    out: dict[str, dict[str, Any]] = {}
    if online:
        out["ONLINE"] = {**base, "offer": offer(online, {"offerType": "ONLINE", "warehouseId": 1})}
    if store:
        out["OFFLINE"] = {
            **base,
            "offer": offer(store, {"offerType": "OFFLINE", "region": "national"}),
        }
    return out


CATALOGUE: dict[int, dict[str, dict[str, Any]]] = {}
for d in [
    detail(
        100025235,
        "Broccoli",
        ["Fruits & vegetables"],
        online=("1.90", "1.90", "250–500 g"),
        store=("4.80", "4.80", "1 kg"),
    ),
    detail(
        100100974,
        "Natural yogurt",
        ["Dairy", "Yogurt"],
        online=("1.80", "1.80", "180 g"),
        store=("1.80", "1.80", "180 g"),
        nutrients={
            "Energy": "~ 309 kJ (~ 74 kcal)",
            "Fat": "3.5 g",
            "of which saturates": "2.3 g",
            "Carbohydrate": "5 g",
            "of which sugars": "4.5 g",
            "Protein": "4 g",
            "Salt": "0.1 g",
        },
    ),
    detail(
        100100975,
        "Strawberry yogurt",
        ["Dairy", "Yogurt"],
        online=("2.20", "1.90", "6 x 125 g"),
        store=("2.20", "2.20", "6 x 125 g"),
        nutrients={
            "Fat": "3 g",
            "of which saturates": "2 g",
            "of which sugars": "12.5 g",
            "Salt": "0.1 g",
        },
    ),
    detail(
        100200001,
        "Spaghetti",
        ["Pasta, rice & grains"],
        online=("2.40", "2.40", "500 g"),
        store=("1.20", "1.20", "500 g"),
    ),
    detail(
        100200002,
        "Wholegrain spaghetti",
        ["Pasta, rice & grains"],
        online=("2.90", "2.90", "500 g"),
        store=("1.60", "1.60", "500 g"),
    ),
    detail(
        100300001,
        "Fresh dill",
        ["Fruits & vegetables", "Herbs"],
        online=None,
        store=("2.50", "2.50", "20 g"),
        availability="INSTORE_ONLY",
    ),
    detail(
        100400001,
        "Peas frozen",
        ["Frozen", "Vegetables"],
        online=("3.20", "3.20", "750 g"),
        store=("3.20", "3.20", "750 g"),
    ),
]:
    uid = int(next(iter(d.values()))["uid"])
    CATALOGUE[uid] = d

SEARCH_INDEX: dict[str, list[int]] = {
    "broccoli": [100025235],
    "yogurt": [100100974, 100100975],
    "natural yogurt": [100100974, 100100975],
    "pasta": [100200001, 100200002],
    "spaghetti": [100200001, 100200002],
    "dill": [100300001],
    "peas": [100400001],
}


class MockMigros:
    """Stateful mock. ``lists`` maps list id -> {product_id: (quantity, availability)}."""

    def __init__(self) -> None:
        self.lists: dict[int, dict[str, tuple[int, str]]] = {97185194: {}, 97185195: {}}
        self.names = {97185194: "In-Person Shopping", 97185195: "Online basket"}
        self.availability: dict[str, str] = {"100400001": "INSUFFICIENT_STOCK"}
        self.puts: list[dict[str, Any]] = []
        self.router = respx.MockRouter(assert_all_called=False, base_url=WWW)
        self._wire()

    def _wire(self) -> None:
        r = self.router
        r.get("/authentication/public/v1/api/guest").mock(
            return_value=httpx.Response(200, headers={"leshopch": "guest-token"}, json={})
        )
        r.post("/onesearch-oc-seaapi/public/v5/search").mock(side_effect=self._search)
        r.get("/product-display/public/v2/product-detail").mock(side_effect=self._detail)
        r.get("/shopping-list/public/v1/lists/overview").mock(side_effect=self._overview)
        r.get("/shopping-list/public/v2/list/details").mock(side_effect=self._details)
        r.put("/shopping-list/public/v3/items").mock(side_effect=self._put_items)

    def _search(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        q = body.get("query", "").lower()
        ids = SEARCH_INDEX.get(q) or [
            uid for term, uids in SEARCH_INDEX.items() if q in term for uid in uids
        ]
        return httpx.Response(200, json={"productIds": ids, "numberOfProducts": len(ids)})

    def _detail(self, request: httpx.Request) -> httpx.Response:
        params = request.url.params
        store_type = params.get("storeType", "OFFLINE")
        uids = [u for u in params.get("uids", "").split(",") if u.isdigit()]
        out = [
            CATALOGUE[int(u)][store_type]
            for u in uids
            if int(u) in CATALOGUE and store_type in CATALOGUE[int(u)]
        ]
        return httpx.Response(200, json=out)

    def _overview(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "shoppingListId": lid,
                    "shoppingListName": self.names[lid],
                    "itemsCount": len(items),
                    "isOwner": True,
                }
                for lid, items in self.lists.items()
            ],
        )

    def _list_json(self, lid: int) -> dict[str, Any]:
        items = [
            {"id": pid, "type": "PRODUCT", "quantity": qty, "ecomProductAvailability": avail}
            for pid, (qty, avail) in self.lists[lid].items()
            if not pid.startswith("text:")
        ]
        texts = [
            {"id": pid[5:], "type": "FREE_TEXT", "name": pid[5:], "quantity": qty}
            for pid, (qty, _) in self.lists[lid].items()
            if pid.startswith("text:")
        ]
        return {
            "shoppingListId": lid,
            "name": self.names[lid],
            "categories": [{"id": 1, "name": "Items", "items": items + texts}]
            if items or texts
            else [],
            "totals": {
                "instoreTotal": 0,
                "onlineTotal": {"estimatedTotal": 0, "minimumOrderValueReached": False},
            },
        }

    def _details(self, request: httpx.Request) -> httpx.Response:
        lid = int(request.url.params.get("shoppingListId", "0"))
        if lid not in self.lists:
            return httpx.Response(404, json={"status": 404})
        return httpx.Response(200, json=self._list_json(lid))

    def _put_items(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.puts.append(body)
        lid = int(body["shoppingListId"])
        for item in body["items"]:
            key = (
                str(item["id"])
                if item.get("type") == "PRODUCT"
                else f"text:{item.get('name') or item['id']}"
            )
            if int(item["quantity"]) <= 0:
                self.lists[lid].pop(key, None)
            else:
                self.lists[lid][key] = (
                    int(item["quantity"]),
                    self.availability.get(key, "AVAILABLE"),
                )
        return httpx.Response(200, json=self._list_json(lid))
