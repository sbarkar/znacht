"""Given the seed rules, a pantry and fixture catalogues, the pipeline must produce a plan
that satisfies the rules, a correct online/in-store split for a Monday-evening delivery,
an online basket at or above the minimum without staple padding, and lists that reconcile
with the week's needs with zero findings (ADR-0016)."""

from __future__ import annotations

from collections import Counter

import pytest

from znacht.domain.plan import Week
from znacht.domain.product import Channel
from znacht.domain.recipe import Spiciness, Tag
from znacht.planner import RuleBasedPlanner
from znacht.services.allocation import need_index, summed
from znacht.services.pipeline import PlanStatus, apply_week, run_week
from znacht.services.reconcile import reconcile
from znacht_memory import MemoryMealPlanSink
from znacht_memory.fixtures import GOLDEN_WEEK_START, grocery_store, recipe_source, recipes

RECIPES = {r.id.key: r for r in recipes()}


@pytest.fixture
async def result(household):
    return await run_week(
        household,
        Week(start=GOLDEN_WEEK_START),
        recipes=recipe_source(),
        store=grocery_store(),
        sink=MemoryMealPlanSink(),
        planner=RuleBasedPlanner(),
    )


async def test_plan_satisfies_the_rules(result, household):
    assert result.status == PlanStatus.NEEDS_APPROVAL, result.violations
    dinners = result.plan.dinners()
    assert len(dinners) == 7
    tags = Counter(tag for m in dinners for tag in RECIPES[m.recipe_id.key].tags)
    assert tags[Tag.FISH] >= 2
    assert tags[Tag.RED_MEAT] == 1
    assert tags[Tag.LEGUMES] >= 2
    for meal in dinners:
        recipe = RECIPES[meal.recipe_id.key]
        assert not recipe.contains("dill")
        assert recipe.spiciness != Spiciness.HOT
        assert meal.servings == household.servings


async def test_split_is_correct_for_a_monday_evening_delivery(result):
    s = result.shopping
    assert s.slot is not None and s.slot.id == "mon-19-21"
    monday = s.slot.delivery_day
    for c in s.online:
        assert c.needed_on > monday
        assert c.deliverable is True
        assert c.channel == Channel.ONLINE
    non_deliverable_in_store = [c for c in s.in_store if c.deliverable is False]
    assert non_deliverable_in_store, "fresh non-deliverable items must land in store"
    assert all(c.channel == Channel.STORE for c in s.in_store)
    assert any(c.needed_on == monday for c in s.in_store), "Monday dinner is bought in store"


async def test_online_basket_meets_minimum_without_staple_padding(result, household):
    s = result.shopping
    assert s.meets_minimum, (s.online_subtotal, s.minimum_order, result.minimum_order)
    need_keys = {(n.name, n.needed_on) for n in result.needs}
    for c in s.online:
        assert (c.need_name, c.needed_on) in need_keys, "every online line comes from a need"
    pantry = household.pantry.as_dict()
    for c in s.online:
        assert not (c.product.staple and c.need_name in pantry), "no padding with pantry staples"
    assert s.deposit == household.store_policy.freezer_box_deposit  # frozen peas are online
    assert s.online_total == s.online_subtotal + s.deposit


async def test_optimiser_switches_flags_and_guards(result):
    by_need = {c.need_name: c for c in (*result.shopping.online, *result.shopping.in_store)}
    assert by_need["yogurt"].switched and by_need["yogurt"].product.id == "p-yog-natural"
    assert by_need["pasta"].flagged and by_need["pasta"].product.id == "p-pasta-white"
    assert by_need["milk"].product.id == "p-milk-whole"
    assert by_need["minced beef"].flagged and by_need["minced beef"].product.id == "p-beef-15"
    assert result.new_preferred["yogurt"] == "p-yog-natural"
    assert "hummus" not in by_need and "tahini" in by_need


async def test_free_text_and_diffs_and_apply(result, household):
    assert "dishwasher tabs" in result.shopping.free_text
    assert result.plan_diff is not None and len(result.plan_diff.add) == 7
    assert result.online_diff is not None and not result.online_diff.is_empty
    assert result.in_store_diff is not None and not result.in_store_diff.is_empty

    store, sink = grocery_store(), MemoryMealPlanSink()
    applied = await apply_week(result, store=store, sink=sink, approved=True)
    assert applied.status == PlanStatus.APPLIED
    assert len(sink.meals) == 7
    online = await store.read_list(household.store_lists.online)
    assert {line.product_id for line in online.lines} == {
        c.product.id for c in result.shopping.online
    }


async def test_switch_is_reverted_when_the_new_product_is_out_of_stock(household):
    from znacht.domain.product import ProductId, StockStatus

    store = grocery_store()
    store.set_stock(ProductId("p-yog-natural"), StockStatus.OUT)
    result = await run_week(
        household,
        Week(start=GOLDEN_WEEK_START),
        recipes=recipe_source(),
        store=store,
        sink=MemoryMealPlanSink(),
        planner=RuleBasedPlanner(),
    )
    yogurt = next(c for c in result.shopping.online if c.need_name == "yogurt")
    assert yogurt.product.id == "p-yog-sweet"
    assert not yogurt.switched
    assert "out of stock" in yogurt.reason
    assert "yogurt" not in result.new_preferred


async def test_generated_plan_reconciles_with_zero_findings(result):
    s = result.shopping
    assert reconcile(s) == []
    assert result.open_findings() == [] and result.overrides == ()
    index = need_index(s)
    assert {n.key for n in s.needs} == {n.key for n in result.needs}
    for line in s.lines:  # every line traces to this week's needs
        assert line.traceable and line.need_keys and all(k in index for k in line.need_keys)
    for name in {n.name for n in s.needs}:  # and no ingredient is bought twice over
        lines = [c for c in s.lines if c.need_name == name]
        if not lines:
            continue
        bought, needed = (
            summed(c.bought for c in lines),
            summed(n.quantity for n in s.needs if n.name == name),
        )
        if all(c.product.pack.compatible(needed) for c in lines):
            largest = max(c.product.pack.base_value for c in lines)
            assert bought.base_value - needed.base_value <= largest, name
