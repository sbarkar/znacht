"""Reconciliation (ADR-0016): quantities once across both lists, findings, the approval gate."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.conftest import EXAMPLE
from znacht.config import load_household
from znacht.domain.delivery import DeliverySlot
from znacht.domain.diff import ShoppingListRef
from znacht.domain.household import Pantry, PantryItem
from znacht.domain.money import Money
from znacht.domain.plan import Meal, MealPlan, MealSlot, Week
from znacht.domain.product import Channel, Product, ProductId
from znacht.domain.quantity import Quantity
from znacht.domain.recipe import Category, Ingredient, Recipe, RecipeId
from znacht.domain.reconcile import FindingKind
from znacht.domain.shopping import ProductChoice
from znacht.planner import RuleBasedPlanner
from znacht.services.allocation import add_backup, need_index, summed
from znacht.services.pipeline import (
    PlanStatus,
    WeekResult,
    apply_week,
    rediff,
    resolve_findings,
    run_week,
)
from znacht.services.reconcile import UnreconciledPlan, open_findings, reconcile
from znacht_memory import MemoryMealPlanSink, MemoryRecipeSource
from znacht_memory.store import MemoryGroceryStore

MONDAY = date(2026, 11, 2)
WEEK = Week(start=MONDAY)
HOUSEHOLD = load_household(EXAMPLE).model_copy(update={"preferred_products": {}})
SERVINGS = HOUSEHOLD.servings
LISTS = [
    ShoppingListRef(id="list-online", name="Online basket", kind="online"),
    ShoppingListRef(id="list-store", name="In store", kind="in_store"),
]


def _slot(day: date) -> DeliverySlot:
    return DeliverySlot(
        id="evening",
        start=datetime(day.year, day.month, day.day, 19),
        end=datetime(day.year, day.month, day.day, 21),
    )


def _product(name: str, pack: str, online: str = "2.00", store: str = "2.20") -> Product:
    return Product(
        id=ProductId(f"p-{name.replace(' ', '-')}"),
        name=name,
        store="memory",
        category=Category.PRODUCE,
        pack=Quantity.parse(pack),
        price_online=Money.chf(online),
        price_store=Money.chf(store),
    )


async def _week(
    uses: dict[date, list[tuple[str, str]]],
    products: list[Product],
    *,
    slot_day: date = MONDAY,
    household=HOUSEHOLD,
) -> WeekResult:
    """Price a fixed week: on each day one dinner using ``uses`` (ingredient, quantity)."""
    recipes = [
        Recipe(
            id=RecipeId(source="memory", external_id=f"dinner-{day:%a}"),
            title=f"Dinner {day:%a}",
            servings=SERVINGS,
            ingredients=tuple(
                Ingredient(name=name, quantity=Quantity.parse(qty), category=Category.PRODUCE)
                for name, qty in items
            ),
        )
        for day, items in sorted(uses.items())
    ]
    plan = MealPlan(
        week=WEEK,
        meals=tuple(
            Meal(date=day, slot=MealSlot.DINNER, recipe_id=r.id, servings=SERVINGS)
            for day, r in zip(sorted(uses), recipes, strict=True)
        ),
    )
    return await run_week(
        household,
        WEEK,
        recipes=MemoryRecipeSource(recipes),
        store=MemoryGroceryStore(products, lists=LISTS, minimum_order=Money.zero()),
        sink=MemoryMealPlanSink(),
        planner=RuleBasedPlanner(),
        slot=_slot(slot_day),
        fixed_plan=plan,
        stop_on_violations=False,
    )


def _totals(result: WeekResult, name: str) -> tuple[Decimal, Decimal, Decimal]:
    """(bought, needed, largest pack) for one ingredient, in grams or millilitres."""
    lines = [c for c in result.shopping.lines if c.need_name == name]
    bought = summed(c.bought for c in lines)
    needed = summed(n.quantity for n in result.shopping.needs if n.name == name)
    assert needed is not None
    largest = max((c.product.pack.base_value for c in lines), default=Decimal(0))
    return (bought.base_value if bought else Decimal(0)), needed.base_value, largest


CARROTS = _product("carrots", "1 kg")
THU = MONDAY + timedelta(days=3)


# --- quantity logic ----------------------------------------------------------------------


async def test_one_pack_bought_in_store_covers_a_need_after_the_delivery():
    """The carrot shape: needed on the delivery day (in store) and later (online). Packs are
    counted once from the summed 0.5 kg, so the in-store kilo covers Thursday too."""
    result = await _week({MONDAY: [("carrots", "250 g")], THU: [("carrots", "250 g")]}, [CARROTS])
    carrots = [c for c in result.shopping.lines if c.need_name == "carrots"]
    assert [(c.channel, c.packs) for c in carrots] == [(Channel.STORE, 1)]
    assert set(carrots[0].need_keys) == {n.key for n in result.shopping.needs}
    assert reconcile(result.shopping) == []


async def test_a_split_across_both_lists_is_computed_from_the_total_and_says_why():
    result = await _week({MONDAY: [("carrots", "250 g")], THU: [("carrots", "1750 g")]}, [CARROTS])
    by_channel = {c.channel: c for c in result.shopping.lines}
    assert by_channel[Channel.STORE].packs == 1
    assert by_channel[Channel.ONLINE].packs == 1  # 2 kg needed, 1 kg already bought in store
    assert all(c.split_reason for c in by_channel.values())
    assert reconcile(result.shopping) == []


async def test_a_backup_in_store_takes_its_packs_off_the_online_basket():
    result = await _week({MONDAY: [("carrots", "250 g")], THU: [("carrots", "1750 g")]}, [CARROTS])
    backed = add_backup(result.shopping, "carrots", 1)
    assert [c.packs for c in backed.online if c.need_name == "carrots"] == []
    assert [c.packs for c in backed.in_store if c.need_name == "carrots"] == [2]
    assert _bought(backed, "carrots") == _bought(result.shopping, "carrots")
    assert reconcile(backed) == []

    partial = await _week({THU: [("carrots", "1750 g")]}, [CARROTS])
    half = add_backup(partial.shopping, "carrots", 1)
    assert [c.packs for c in half.online] == [1] and [c.packs for c in half.in_store] == [1]
    assert all(c.split_reason for c in half.lines)
    assert reconcile(half) == []
    with pytest.raises(ValueError):
        add_backup(partial.shopping, "carrots", 3)
    with pytest.raises(LookupError):
        add_backup(partial.shopping, "leeks")


def _bought(plan, name):
    return summed(c.bought for c in plan.lines if c.need_name == name)


# --- the carrot regression (ADR-0016) -------------------------------------------------------


def _incident(result: WeekResult) -> WeekResult:
    """Last week's lists, rebuilt on this week's needs: 2 kg on the online basket for Thursday,
    and 1 kg added to the in-store list as a backup without taking anything off online."""
    s = result.shopping
    store_line = next(c for c in s.in_store if c.need_name == "carrots")
    thursday = next(n for n in s.needs if n.name == "carrots" and n.needed_on == THU)
    online = store_line.model_copy(
        update={
            "channel": Channel.ONLINE,
            "packs": 2,
            "needed_on": THU,
            "need_keys": (thursday.key,),
            "split_reason": None,
        }
    )
    backup = store_line.model_copy(update={"split_reason": "backup in case delivery comes late"})
    return result.model_copy(
        update={"shopping": s.model_copy(update={"online": (online,), "in_store": (backup,)})}
    )


async def test_carrot_incident_is_flagged_and_blocks_approval(caplog):
    result = await _week({MONDAY: [("carrots", "250 g")], THU: [("carrots", "250 g")]}, [CARROTS])
    assert result.status == PlanStatus.NEEDS_APPROVAL and result.open_findings() == []

    incident = _incident(result)
    findings = reconcile(incident.shopping)
    surplus = [f for f in findings if f.kind == FindingKind.SURPLUS]
    assert [f.message for f in surplus] == [
        "carrots: 3 kg bought vs 0.5 kg needed (online 2 kg + in-store 1 kg)"
    ]
    assert surplus[0].excess_packs == Decimal("2.5")
    cross = [f for f in findings if f.kind == FindingKind.CROSS_LIST]
    assert len(cross) == 1 and "3 kg combined (online 2 kg + in-store 1 kg)" in cross[0].message

    store, sink = MemoryGroceryStore([CARROTS], lists=LISTS), MemoryMealPlanSink()
    with pytest.raises(UnreconciledPlan) as refused:
        await apply_week(incident, store=store, sink=sink, approved=True)
    assert "carrots: 3 kg bought" in str(refused.value)
    assert not store.applied and not sink.meals

    # fixed: the quantities are computed again from the summed need
    fixed = resolve_findings(incident, fix=[f.id for f in findings])
    assert fixed.open_findings() == []
    assert _bought(fixed.shopping, "carrots") == Quantity.parse("1 kg").to_base()
    fixed = await rediff(fixed, store=store)
    assert [line.line.quantity for line in fixed.in_store_diff.lines if line.line.product_id] == [1]
    assert all(not d.line.product_id for d in fixed.online_diff.lines)
    assert (await apply_week(fixed, store=store, sink=sink, approved=True)).status == "applied"

    # or overridden with a reason: logged and kept with the run
    with caplog.at_level(logging.WARNING, logger="znacht.services.reconcile"):
        overridden = resolve_findings(
            incident, overrides={f.id: "carrot cake for the school fair" for f in findings}
        )
    assert overridden.open_findings() == []
    assert [o.reason for o in overridden.overrides] == ["carrot cake for the school fair"] * 2
    assert any("carrot cake" in n for n in overridden.notes)
    assert "3 kg bought vs 0.5 kg needed" in caplog.text
    applied = await apply_week(
        overridden, store=MemoryGroceryStore([CARROTS], lists=LISTS), sink=sink, approved=True
    )
    assert applied.status == PlanStatus.APPLIED


async def test_an_override_stops_covering_a_finding_once_the_numbers_change():
    result = _incident(
        await _week({MONDAY: [("carrots", "250 g")], THU: [("carrots", "250 g")]}, [CARROTS])
    )
    surplus = next(f for f in result.findings() if f.kind == FindingKind.SURPLUS)
    overridden = resolve_findings(result, overrides={surplus.id: "for the rabbit"})
    assert surplus not in overridden.open_findings()
    s = overridden.shopping
    more = s.model_copy(update={"online": (s.online[0].model_copy(update={"packs": 4}),)})
    bigger = overridden.model_copy(update={"shopping": more})
    assert any(f.id == surplus.id for f in bigger.open_findings())


async def test_resolve_refuses_unknown_findings_and_empty_reasons():
    result = _incident(
        await _week({MONDAY: [("carrots", "250 g")], THU: [("carrots", "250 g")]}, [CARROTS])
    )
    with pytest.raises(LookupError):
        resolve_findings(result, fix=["surplus:leeks"])
    surplus = next(f for f in result.findings() if f.kind == FindingKind.SURPLUS)
    with pytest.raises(ValueError):
        resolve_findings(result, overrides={surplus.id: "  "})
    with pytest.raises(ValueError):
        resolve_findings(result, fix=[surplus.id], overrides={surplus.id: "both"})


# --- traceability --------------------------------------------------------------------------


async def test_every_line_traces_to_needs_and_orphans_are_findings():
    result = await _week(
        {MONDAY: [("carrots", "250 g")], THU: [("leeks", "300 g")]},
        [
            CARROTS,
            _product("leeks", "500 g"),
        ],
    )
    index = need_index(result.shopping)
    for line in result.shopping.lines:
        assert line.traceable and all(k in index for k in line.need_keys)

    stray = ProductChoice(
        need_name="chocolate",
        product=_product("chocolate", "100 g"),
        packs=3,
        needed_on=THU,
        channel=Channel.ONLINE,
        reason="added by hand",
    )
    household = stray.model_copy(update={"manual_reason": "household: weekend treat"})
    for extra, expected in ((stray, 1), (household, 0)):
        s = result.shopping.model_copy(update={"online": (*result.shopping.online, extra)})
        orphans = [f for f in reconcile(s) if f.kind == FindingKind.ORPHAN]
        assert len(orphans) == expected
    orphan = next(
        f
        for f in reconcile(result.shopping.model_copy(update={"online": (stray,)}))
        if f.kind == FindingKind.ORPHAN
    )
    assert orphan.message == (
        "chocolate: 3 × chocolate on the online list traces to no recipe need and gives no reason"
    )


async def test_the_pantry_is_deducted_before_packs_and_named_in_the_message():
    household = HOUSEHOLD.model_copy(
        update={
            "pantry": Pantry(items=(PantryItem(name="carrots", quantity=Quantity.parse("200 g")),))
        }
    )
    result = await _week(
        {MONDAY: [("carrots", "700 g")], THU: [("carrots", "500 g")]},
        [CARROTS],
        household=household,
    )
    bought, needed, _ = _totals(result, "carrots")
    assert needed == 1000 and bought == 1000
    s = result.shopping
    extra = s.model_copy(
        update={"in_store": tuple(c.model_copy(update={"packs": 3}) for c in s.in_store)}
    )
    [finding] = reconcile(extra)
    assert finding.message == (
        "carrots: 3 kg bought vs 1 kg needed (in-store 3 kg); 200 g in the pantry already counted"
    )


async def test_the_threshold_is_configurable():
    strict = HOUSEHOLD.model_copy(
        update={
            "store_policy": HOUSEHOLD.store_policy.model_copy(
                update={"surplus_threshold_packs": Decimal("0.5")}
            )
        }
    )
    result = await _week({MONDAY: [("carrots", "250 g")]}, [CARROTS], household=strict)
    assert result.shopping.surplus_threshold_packs == Decimal("0.5")
    [finding] = reconcile(result.shopping)  # 1 kg for 250 g is 0.75 packs over
    assert finding.kind == FindingKind.SURPLUS
    assert finding.message == "carrots: 1 kg bought vs 0.25 kg needed (in-store 1 kg)"


async def test_reconcile_is_deterministic():
    result = _incident(
        await _week({MONDAY: [("carrots", "250 g")], THU: [("carrots", "250 g")]}, [CARROTS])
    )
    shuffled = result.shopping.model_copy(update={"needs": tuple(reversed(result.shopping.needs))})
    assert reconcile(result.shopping) == reconcile(result.shopping) == reconcile(shuffled)


# --- property: never more than one pack beyond need, unless overridden ----------------------

NAMES = ("carrots", "leeks", "flour")
DAYS = [MONDAY + timedelta(days=i) for i in range(7)]

uses_strategy = st.dictionaries(
    st.sampled_from(DAYS),
    st.lists(
        st.tuples(st.sampled_from(NAMES), st.integers(min_value=10, max_value=3000)),
        min_size=1,
        max_size=3,
        unique_by=lambda t: t[0],
    ),
    min_size=1,
    max_size=7,
)
packs_strategy = st.fixed_dictionaries(
    {name: st.sampled_from([100, 250, 400, 500, 750, 1000, 2500]) for name in NAMES}
)
store_packs_strategy = st.fixed_dictionaries(
    {name: st.sampled_from([None, 200, 500, 1000]) for name in NAMES}
)


def _catalogue(online_packs, store_packs, prices):
    """One product per ingredient, and sometimes a second, cheaper-in-store one in another pack,
    so the two lists can pick different packs for the same ingredient."""
    out = []
    for name in NAMES:
        online, store = prices[name]
        out.append(_product(name, f"{online_packs[name]} g", online, store))
        if store_packs[name] is not None:
            out.append(
                _product(f"{name} value", f"{store_packs[name]} g", "9.00", "0.10").model_copy(
                    update={"id": ProductId(f"p-{name}-value")}
                )
            )
    return out


@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(
    uses=uses_strategy,
    online_packs=packs_strategy,
    store_packs=store_packs_strategy,
    slot_offset=st.integers(min_value=-1, max_value=6),
    pantry_g=st.integers(min_value=0, max_value=1500),
    prices=st.fixed_dictionaries(
        {
            name: st.sampled_from([("2.00", "2.20"), ("3.00", "1.00"), ("1.00", "3.00")])
            for name in NAMES
        }
    ),
    backups=st.lists(st.tuples(st.sampled_from(NAMES), st.integers(1, 3)), max_size=3),
)
def test_property_total_minus_need_is_at_most_one_pack(
    uses, online_packs, store_packs, slot_offset, pantry_g, prices, backups
):
    household = HOUSEHOLD.model_copy(
        update={
            "pantry": Pantry(
                items=(PantryItem(name="flour", quantity=Quantity.parse(f"{pantry_g} g")),)
                if pantry_g
                else ()
            )
        }
    )
    result = asyncio.run(
        _week(
            {day: [(n, f"{g} g") for n, g in items] for day, items in uses.items()},
            _catalogue(online_packs, store_packs, prices),
            slot_day=MONDAY + timedelta(days=slot_offset),
            household=household,
        )
    )
    shopping = result.shopping
    for name, packs in backups:  # a backup moves packs; it never adds any
        line = next((c for c in shopping.online if c.need_name == name), None)
        if line is not None:
            shopping = add_backup(shopping, name, min(packs, line.packs))
    for name in {n.name for n in shopping.needs}:
        lines = [c for c in shopping.lines if c.need_name == name]
        if not lines:
            continue  # no product matched (would be on the free-text list)
        bought = summed(c.bought for c in lines)
        needed = summed(n.quantity for n in shopping.needs if n.name == name)
        assert bought is not None and needed is not None
        assert bought.base_value >= needed.base_value, (name, lines)
        largest = max(c.product.pack.base_value for c in lines)
        assert bought.base_value - needed.base_value <= largest, (name, bought, needed, lines)
    assert reconcile(shopping) == [], reconcile(shopping)


@settings(max_examples=60, deadline=None)
@given(
    uses=uses_strategy,
    online_packs=packs_strategy,
    extra=st.lists(
        st.tuples(st.sampled_from(NAMES), st.sampled_from(list(Channel)), st.integers(1, 4)),
        min_size=1,
        max_size=4,
    ),
)
def test_property_over_buying_is_flagged_until_overridden(uses, online_packs, extra):
    """Lines added past the allocation (by hand, or an old per-list rounding): whatever ends
    more than one pack over is a surplus finding, and the plan applies only once overridden."""
    result = asyncio.run(
        _week(
            {day: [(n, f"{g} g") for n, g in items] for day, items in uses.items()},
            _catalogue(online_packs, dict.fromkeys(NAMES), {n: ("2.00", "2.20") for n in NAMES}),
        )
    )
    s = result.shopping
    added = list(s.lines)
    for name, channel, packs in extra:
        model = next((c for c in s.lines if c.need_name == name), None)
        if model is not None:
            added.append(
                model.model_copy(update={"channel": channel, "packs": packs, "split_reason": "x"})
            )
    s = s.model_copy(
        update={
            "online": tuple(c for c in added if c.channel == Channel.ONLINE),
            "in_store": tuple(c for c in added if c.channel == Channel.STORE),
        }
    )
    findings = reconcile(s)
    flagged = {f.need_name for f in findings if f.kind == FindingKind.SURPLUS}
    for name in {n.name for n in s.needs}:
        lines = [c for c in s.lines if c.need_name == name]
        if not lines:
            continue
        bought = summed(c.bought for c in lines)
        needed = summed(n.quantity for n in s.needs if n.name == name)
        largest = max(c.product.pack.base_value for c in lines)
        over = bought.base_value - needed.base_value > largest
        assert (name in flagged) == over, (name, bought, needed, largest)
    candidate = result.model_copy(update={"shopping": s})
    assert candidate.open_findings() == findings
    if findings:
        with pytest.raises(UnreconciledPlan):
            asyncio.run(
                apply_week(
                    candidate,
                    store=MemoryGroceryStore([], lists=LISTS),
                    sink=MemoryMealPlanSink(),
                    approved=True,
                )
            )
    overridden = resolve_findings(candidate, overrides={f.id: "on purpose" for f in findings})
    assert open_findings(reconcile(overridden.shopping), overridden.overrides) == []
