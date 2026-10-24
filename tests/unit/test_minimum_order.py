from datetime import date, datetime

from hypothesis import given
from hypothesis import strategies as st

from znacht.domain.delivery import DeliverySlot
from znacht.domain.money import Money
from znacht.domain.product import Channel, Product, ProductId
from znacht.domain.quantity import Quantity
from znacht.domain.recipe import Category
from znacht.domain.shopping import ProductChoice, ShoppingPlan
from znacht.services.minimum_order import ensure_minimum_order

SLOT = DeliverySlot(id="mon", start=datetime(2026, 10, 26, 19), end=datetime(2026, 10, 26, 21))


def _choice(
    name: str, online: str, store: str, *, movable: bool, staple: bool = False
) -> ProductChoice:
    product = Product(
        id=ProductId(f"p-{name}"),
        name=name,
        store="memory",
        category=Category.PANTRY if staple else Category.OTHER,
        pack=Quantity.parse("1"),
        price_online=Money.chf(online),
        price_store=Money.chf(store),
        staple=staple,
    )
    return ProductChoice(
        need_name=name,
        product=product,
        packs=1,
        needed_on=date(2026, 10, 29),
        channel=Channel.STORE,
        reason="t",
        movable=movable,
        deliverable=True,
    )


def test_moves_movable_lines_cheapest_penalty_first():
    plan = ShoppingPlan(
        slot=SLOT,
        online=(),
        in_store=(
            _choice("a", "10", "8", movable=True),  # penalty 2
            _choice("b", "10", "9.5", movable=True),  # penalty 0.5
            _choice("c", "50", "1", movable=False),  # not movable
            _choice("oil", "9", "9", movable=True, staple=True),  # a staple the plan needs may move
        ),
        minimum_order=Money.chf(15),
    )
    result, report = ensure_minimum_order(plan)
    assert report.met
    assert report.moved_online == ("oil", "b")
    assert result.meets_minimum
    assert {c.need_name for c in result.in_store} == {"a", "c"}


def test_asks_household_when_still_short_and_never_adds_lines():
    plan = ShoppingPlan(
        slot=SLOT, in_store=(_choice("a", "10", "8", movable=True),), minimum_order=Money.chf(99)
    )
    result, report = ensure_minimum_order(plan)
    assert not report.met
    assert report.ask_household == Money.chf(89)
    assert len(result.online) + len(result.in_store) == 1


@given(
    prices=st.lists(st.decimals(min_value="0.05", max_value=50, places=2), min_size=0, max_size=12),
    minimum=st.decimals(min_value=0, max_value=200, places=2),
)
def test_top_up_only_moves_and_total_is_monotonic(prices, minimum):
    in_store = tuple(
        _choice(f"n{i}", str(p), str(p), movable=i % 2 == 0) for i, p in enumerate(prices)
    )
    plan = ShoppingPlan(slot=SLOT, in_store=in_store, minimum_order=Money.chf(minimum))
    result, report = ensure_minimum_order(plan)
    assert len(result.online) + len(result.in_store) == len(in_store)
    assert result.online_subtotal >= plan.online_subtotal
    assert report.met == result.meets_minimum
    assert all(c.channel == Channel.ONLINE for c in result.online)
