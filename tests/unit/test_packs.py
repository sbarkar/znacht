from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from znacht.domain.quantity import Quantity, Unit
from znacht.services.packs import packs_needed


@given(
    need=st.decimals(min_value="0.01", max_value=50_000, places=2),
    pack=st.decimals(min_value="0.01", max_value=5_000, places=2),
)
def test_packs_cover_the_need_without_one_pack_too_many(need: Decimal, pack: Decimal):
    n = packs_needed(Quantity.of(need, Unit.G), Quantity.of(pack, Unit.G))
    assert n >= 1
    assert n * pack >= need
    assert (n - 1) * pack < need


def test_zero_need_means_zero_packs():
    assert packs_needed(Quantity.of(0, Unit.G), Quantity.of(100, Unit.G)) == 0


def test_mixed_units_within_a_family():
    assert packs_needed(Quantity.parse("375 g"), Quantity.parse("0.225 kg")) == 2
    assert packs_needed(Quantity.parse("1 l"), Quantity.parse("400 ml")) == 3
