from decimal import Decimal

import pytest

from tests.migros.mock_server import CATALOGUE
from znacht.domain.quantity import Unit
from znacht.domain.recipe import Category
from znacht_migros.mapping import parse_nutrition, parse_pack, product_from
from znacht_migros.session import totp_code


@pytest.mark.parametrize(
    ("text", "value", "unit"),
    [
        ("360 g", Decimal(360), Unit.G),
        ("1 kg", Decimal(1), Unit.KG),
        ("250–500 g", Decimal(250), Unit.G),
        ("6 x 125 g", Decimal(750), Unit.G),
        ("2 x 1 l", Decimal(2), Unit.L),
        ("500ml", Decimal(500), Unit.ML),
        ("5 dl", Decimal(500), Unit.ML),
        ("1 piece", Decimal(1), Unit.PIECE),
        ("2 Stück", Decimal(2), Unit.PIECE),
        ("ca. 400 g", Decimal(400), Unit.G),
        (None, Decimal(1), Unit.PIECE),
        ("", Decimal(1), Unit.PIECE),
    ],
)
def test_parse_pack(text, value, unit):
    q = parse_pack(text)
    assert (q.value, q.unit) == (value, unit)


def test_parse_nutrition_reads_the_per_100g_table():
    n = parse_nutrition(
        CATALOGUE[100100974]["ONLINE"]["productInformation"]["nutrientsInformation"]
    )
    assert n is not None
    assert n.energy_kcal == 74
    assert n.fat_g == Decimal("3.5")
    assert n.saturated_fat_g == Decimal("2.3")
    assert n.sugar_g == Decimal("4.5")
    assert n.salt_g == Decimal("0.1")
    assert parse_nutrition(None) is None


def test_product_from_keeps_both_channel_prices_and_packs():
    p = product_from(CATALOGUE[100025235]["ONLINE"], CATALOGUE[100025235]["OFFLINE"])
    assert p.id == "100025235"
    assert p.name == "Migros Broccoli"
    assert p.category == Category.PRODUCE
    assert str(p.price_online) == "CHF 1.90"
    assert str(p.price_store) == "CHF 4.80"
    assert (
        p.pack.value == 250 and p.pack.unit == Unit.G
    )  # online pack wins; lower bound of the range


def test_product_from_detects_promotions_and_wholegrain():
    y = product_from(CATALOGUE[100100975]["ONLINE"], CATALOGUE[100100975]["OFFLINE"])
    assert y.promotions and str(y.promotions[0].price) == "CHF 1.90"
    assert str(y.price_online) == "CHF 2.20"  # list price
    assert y.pack.value == 750
    wg = product_from(CATALOGUE[100200002]["ONLINE"], None)
    assert wg.category == Category.GRAIN and wg.wholegrain is True
    assert product_from(CATALOGUE[100200001]["ONLINE"], None).wholegrain is False
    frozen = product_from(CATALOGUE[100400001]["ONLINE"], None)
    assert frozen.frozen


def test_store_only_product_has_no_online_price():
    dill = product_from(None, CATALOGUE[100300001]["OFFLINE"])
    assert dill.price_online is None and str(dill.price_store) == "CHF 2.50"
    assert dill.category == Category.HERB


def test_totp_matches_rfc6238_vector():
    # RFC 6238 appendix B: secret "12345678901234567890", T=59 -> 287082
    assert totp_code("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", now=59) == "287082"
