from datetime import date, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from znacht.domain.delivery import DeliverySlot
from znacht.domain.needs import IngredientNeed
from znacht.domain.quantity import Quantity, Unit
from znacht.services.split import timing_split

MONDAY = date(2026, 10, 26)


def _need(day: date) -> IngredientNeed:
    return IngredientNeed(name="x", quantity=Quantity.of(1, Unit.G), needed_on=day)


@given(
    offsets=st.lists(st.integers(min_value=0, max_value=6), max_size=20),
    delivery_offset=st.integers(min_value=0, max_value=6),
    end_hour=st.integers(min_value=7, max_value=22),
)
def test_everything_needed_on_or_before_delivery_day_is_in_store(
    offsets, delivery_offset, end_hour
):
    day = MONDAY + timedelta(days=delivery_offset)
    slot = DeliverySlot(
        id="s",
        start=datetime(day.year, day.month, day.day, end_hour - 2),
        end=datetime(day.year, day.month, day.day, end_hour),
    )
    needs = [_need(MONDAY + timedelta(days=o)) for o in offsets]
    online, in_store = timing_split(needs, slot)
    assert len(online) + len(in_store) == len(needs)
    assert all(n.needed_on > day for n in online)
    assert all(n.needed_on <= day for n in in_store)


def test_no_slot_means_everything_in_store():
    online, in_store = timing_split([_need(MONDAY), _need(MONDAY + timedelta(days=3))], None)
    assert online == []
    assert len(in_store) == 2


def test_monday_evening_delivery_keeps_monday_dinner_in_store():
    slot = DeliverySlot(id="mon", start=datetime(2026, 10, 26, 19), end=datetime(2026, 10, 26, 21))
    online, in_store = timing_split([_need(MONDAY), _need(MONDAY + timedelta(days=1))], slot)
    assert [n.needed_on for n in in_store] == [MONDAY]
    assert [n.needed_on for n in online] == [MONDAY + timedelta(days=1)]
