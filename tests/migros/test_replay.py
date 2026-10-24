"""The real adapter against recorded, scrubbed Migros HTTP. No network, no secrets."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.migros.vcr_config import KNOWN_PRODUCT_ID, SEARCH_QUERY, SECOND_QUERY, cassette
from znacht.domain.product import ProductId
from znacht.domain.recipe import Category
from znacht_migros import MigrosGroceryStore, MigrosSession, MigrosSettings


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[MigrosGroceryStore]:
    with cassette("none"):
        session = MigrosSession(MigrosSettings(session_file=tmp_path / "session.json"))
        session.store.jwt, session.store.jwt_exp = "replay", int(time.time()) + 3600
        async with session:
            yield MigrosGroceryStore(session)


async def test_search_replays_real_products_with_both_prices(store: MigrosGroceryStore):
    hits = await store.search(SEARCH_QUERY, limit=3)
    assert hits[0].id == KNOWN_PRODUCT_ID
    broccoli = hits[0]
    assert broccoli.category == Category.PRODUCE
    assert broccoli.price_online is not None and broccoli.price_store is not None
    assert broccoli.price_online != broccoli.price_store  # the two channels really differ
    assert broccoli.pack.base_value > 0
    assert broccoli.url and broccoli.url.startswith("https://www.migros.ch/")


async def test_packaged_product_has_nutrition(store: MigrosGroceryStore):
    hits = await store.search(SECOND_QUERY, limit=3)
    assert hits
    with_nutrition = [h for h in hits if h.nutrition is not None]
    assert with_nutrition, "at least one yogurt carries a per-100 g table"
    assert any(h.nutrition and h.nutrition.sugar_g is not None for h in with_nutrition)
    assert all(h.category in (Category.YOGURT, Category.DAIRY, Category.OTHER) for h in hits)


async def test_product_roundtrip_and_unknown(store: MigrosGroceryStore):
    p = await store.product(ProductId(KNOWN_PRODUCT_ID))
    assert p.id == KNOWN_PRODUCT_ID
    with pytest.raises(LookupError):
        await store.product(ProductId("1"))


async def test_lists_are_read_by_explicit_id(store: MigrosGroceryStore):
    refs = await store.lists()
    assert refs and all(r.id.isdigit() for r in refs)
    first = await store.read_list(refs[0].id)
    assert first.id == refs[0].id
    assert await store.delivery_slots("8000") == []
