"""The Migros adapter passes the GroceryStore contract against the respx mock server."""

import pytest

from znacht.domain.diff import ListDiff, ListLineDiff, ShoppingList, ShoppingListLine
from znacht.domain.product import ProductId, StockStatus
from znacht.testing.contracts import GroceryStoreContract
from znacht_migros import MigrosGroceryStore


class TestMigrosStoreContract(GroceryStoreContract):
    @pytest.fixture
    def store(self, session):
        return MigrosGroceryStore(session)

    @pytest.fixture
    def postcode(self):
        return "8000"

    @pytest.fixture
    def search_term(self):
        return "yogurt"

    @pytest.fixture
    def list_id(self):
        return "97185194"


async def test_search_merges_both_channels(store: MigrosGroceryStore):
    hits = await store.search("broccoli")
    assert len(hits) == 1
    assert str(hits[0].price_online) == "CHF 1.90" and str(hits[0].price_store) == "CHF 4.80"


async def test_deliverability_uses_product_flag_then_learned_feedback(
    store: MigrosGroceryStore, mock
):
    await store.search("dill")
    await store.search("peas")
    before = await store.deliverability([ProductId("100300001"), ProductId("100400001")], "8000")
    assert before[ProductId("100300001")].deliverable is False  # INSTORE_ONLY flag
    assert before[ProductId("100400001")].deliverable is True  # nothing learned yet
    # put peas on a list: Migros answers INSUFFICIENT_STOCK for this address
    diff = ListDiff(
        list_id="97185195",
        lines=(
            ListLineDiff(
                op="add", line=ShoppingListLine(product_id=ProductId("100400001"), quantity=1)
            ),
        ),
    )
    assert (await store.apply_list("97185195", diff)).ok
    after = await store.deliverability([ProductId("100400001")], "8000")
    assert after[ProductId("100400001")].deliverable is False
    assert (await store.stock([ProductId("100400001")]))[ProductId("100400001")] == StockStatus.OUT
    assert store.learned_availability() == {"100400001": "INSUFFICIENT_STOCK"}


async def test_apply_sends_products_then_free_text_with_zero_for_removals(
    store: MigrosGroceryStore, mock
):
    lid = "97185194"
    first = ShoppingList(
        id=lid,
        lines=(
            ShoppingListLine(product_id=ProductId("100200001"), quantity=2),
            ShoppingListLine(text="dishwasher tabs"),
        ),
    )
    await store.apply_list(lid, await store.diff_list(lid, first))
    second = ShoppingList(
        id=lid, lines=(ShoppingListLine(product_id=ProductId("100200002"), quantity=1),)
    )
    await store.apply_list(lid, await store.diff_list(lid, second))
    # products and free text travel in separate requests; removals are quantity 0
    products = next(
        p for p in reversed(mock.puts) if all(i["type"] == "PRODUCT" for i in p["items"])
    )
    texts = next(
        p for p in reversed(mock.puts) if any(i["type"] == "FREE_TEXT" for i in p["items"])
    )
    assert products["shoppingListId"] == 97185194
    by_id = {i["id"]: i for i in products["items"]}
    assert by_id["100200002"]["quantity"] == 1 and by_id["100200002"]["type"] == "PRODUCT"
    assert by_id["100200001"]["quantity"] == 0
    assert texts["items"][0]["id"] == "dishwasher tabs" and texts["items"][0]["quantity"] == 0
    assert (await store.read_list(lid)).as_dict().keys() == {"p:100200002"}


async def test_lists_are_classified_by_name(store: MigrosGroceryStore):
    refs = {r.id: r.kind for r in await store.lists()}
    assert refs == {"97185194": "in_store", "97185195": "online"}


async def test_delivery_slots_are_not_known_yet(store: MigrosGroceryStore):
    assert await store.delivery_slots("8000") == []
