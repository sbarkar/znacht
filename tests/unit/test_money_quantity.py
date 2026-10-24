from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from znacht.domain.money import Money, total
from znacht.domain.quantity import Quantity, Unit


def test_money_rounds_to_cents_and_adds():
    assert Money.chf("1.005").amount == Decimal("1.01")
    assert str(Money.chf(1) + Money.chf("2.5")) == "CHF 3.50"
    assert total([Money.chf(1), Money.chf(2)]) == Money.chf(3)


def test_money_refuses_mixed_currencies():
    with pytest.raises(ValueError):
        Money.chf(1) + Money(amount=Decimal(1), currency="EUR")


def test_quantity_parse_and_convert():
    assert Quantity.parse("1.5kg").to_base() == Quantity.of(1500, Unit.G)
    assert Quantity.parse("2").unit == Unit.PIECE
    assert Quantity.parse("3 pcs").value == 3
    assert Quantity.parse("500 g").ratio(Quantity.parse("0.25 kg")) == 2
    with pytest.raises(ValueError):
        Quantity.parse("500 cups")
    with pytest.raises(ValueError):
        Quantity.parse("1 l") + Quantity.parse("1 g")


@given(
    a=st.decimals(min_value=0, max_value=10_000, places=2),
    b=st.decimals(min_value=0, max_value=10_000, places=2),
)
def test_quantity_minus_floors_at_zero(a: Decimal, b: Decimal):
    result = Quantity.of(a, Unit.G).minus(Quantity.of(b, Unit.KG))
    assert result.value >= 0
    assert result.value == max(Decimal(0), a - b * 1000)
