"""Port contract suites.

Subclass in your adapter's tests and provide the fixtures. The in-memory adapters run the
same suites, so a green contract suite means the adapter behaves like the fakes the core
is tested against.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from znacht.domain.diff import ShoppingList, ShoppingListLine
from znacht.domain.household import Household
from znacht.domain.needs import IngredientNeed
from znacht.domain.plan import Meal, MealPlan, MealSlot, Week
from znacht.domain.product import Channel, Product, ProductId
from znacht.domain.recipe import RecipeId
from znacht.domain.reconcile import Finding, FindingKind
from znacht.domain.shopping import ProductChoice, ShoppingPlan
from znacht.ports.notify import Notifier, PlanEvent
from znacht.ports.planner import PlannerProvider, PlanningContext
from znacht.ports.recipes import RecipeQuery, RecipeSource
from znacht.ports.sinks import MealPlanSink
from znacht.ports.stores import GroceryStore
from znacht.services.lists import shopping_list_from
from znacht.services.reconcile import read_listed_plan, reconcile

FORBIDDEN_METHOD_NAMES = frozenset(
    {
        "checkout",
        "place_order",
        "order",
        "submit_order",
        "pay",
        "payment",
        "purchase",
        "book_slot",
        "reserve_slot",
    }
)


class RecipeSourceContract:
    @pytest.fixture
    def source(self) -> RecipeSource:
        raise NotImplementedError

    @pytest.fixture
    def known_recipe_id(self, source: RecipeSource) -> RecipeId:
        raise NotImplementedError

    async def test_is_a_recipe_source(self, source: RecipeSource) -> None:
        assert isinstance(source, RecipeSource)
        assert source.name

    async def test_search_returns_recipes_with_ingredients(self, source: RecipeSource) -> None:
        hits = await source.search(RecipeQuery(limit=5))
        assert hits
        assert len(hits) <= 5
        for recipe in hits:
            assert recipe.servings > 0
            assert recipe.ingredients

    async def test_search_excludes_ingredients(self, source: RecipeSource) -> None:
        hits = await source.search(RecipeQuery(limit=50))
        name = hits[0].ingredients[0].name
        filtered = await source.search(RecipeQuery(exclude_ingredients=frozenset({name}), limit=50))
        assert all(not r.contains(name) for r in filtered)

    async def test_get_known(self, source: RecipeSource, known_recipe_id: RecipeId) -> None:
        recipe = await source.get(known_recipe_id)
        assert recipe.id == known_recipe_id

    async def test_get_unknown_raises_lookup_error(self, source: RecipeSource) -> None:
        with pytest.raises(LookupError):
            await source.get(RecipeId(source=source.name, external_id="does-not-exist-0000"))


class MealPlanSinkContract:
    @pytest.fixture
    def sink(self) -> MealPlanSink:
        raise NotImplementedError

    @pytest.fixture
    def week(self) -> Week:
        return Week(start=date(2026, 10, 26))

    @pytest.fixture
    def sample_recipe_id(self) -> RecipeId:
        raise NotImplementedError

    async def test_is_a_sink(self, sink: MealPlanSink) -> None:
        assert isinstance(sink, MealPlanSink)

    async def test_read_week_returns_plan_for_week(self, sink: MealPlanSink, week: Week) -> None:
        plan = await sink.read_week(week)
        assert plan.week == week
        assert all(m.date in week for m in plan.meals)

    async def test_diff_is_pure(
        self, sink: MealPlanSink, week: Week, sample_recipe_id: RecipeId
    ) -> None:
        plan = MealPlan(
            week=week,
            meals=(
                Meal(date=week.start, slot=MealSlot.DINNER, recipe_id=sample_recipe_id, servings=2),
            ),
        )
        before = await sink.read_week(week)
        first = await sink.diff(plan)
        second = await sink.diff(plan)
        assert first == second
        assert await sink.read_week(week) == before

    async def test_diff_then_apply_roundtrip(
        self, sink: MealPlanSink, week: Week, sample_recipe_id: RecipeId
    ) -> None:
        plan = MealPlan(
            week=week,
            meals=(
                Meal(date=week.start, slot=MealSlot.DINNER, recipe_id=sample_recipe_id, servings=2),
            ),
        )
        result = await sink.apply(await sink.diff(plan))
        assert result.ok
        # servings are not stored by every sink: compare by (date, recipe)
        read = {(m.date, m.recipe_id.key) for m in (await sink.read_week(week)).meals}
        assert read == {(m.date, m.recipe_id.key) for m in plan.meals}
        assert (await sink.diff(plan)).is_empty
        # clean up
        await sink.apply(await sink.diff(MealPlan(week=week)))


class GroceryStoreContract:
    @pytest.fixture
    def store(self) -> GroceryStore:
        raise NotImplementedError

    @pytest.fixture
    def postcode(self) -> str:
        raise NotImplementedError

    @pytest.fixture
    def search_term(self) -> str:
        raise NotImplementedError

    @pytest.fixture
    def list_id(self) -> str:
        raise NotImplementedError

    async def test_is_a_store(self, store: GroceryStore) -> None:
        assert isinstance(store, GroceryStore)

    def test_has_no_checkout_order_or_payment(self, store: GroceryStore) -> None:
        public = {n for n in dir(store) if not n.startswith("_")}
        assert not (public & FORBIDDEN_METHOD_NAMES), public & FORBIDDEN_METHOD_NAMES

    async def test_search_returns_priced_products(
        self, store: GroceryStore, search_term: str
    ) -> None:
        hits = await store.search(search_term, limit=6)
        assert hits
        assert len(hits) <= 6
        for p in hits:
            assert p.price_online is not None or p.price_store is not None
            assert p.pack.base_value > 0

    async def test_product_roundtrip(self, store: GroceryStore, search_term: str) -> None:
        first = (await store.search(search_term, limit=1))[0]
        assert (await store.product(first.id)).id == first.id

    async def test_unknown_product_raises_lookup_error(self, store: GroceryStore) -> None:
        with pytest.raises(LookupError):
            await store.product(ProductId("does-not-exist-0000"))

    async def test_deliverability_covers_every_id(
        self, store: GroceryStore, search_term: str, postcode: str
    ) -> None:
        ids = [p.id for p in await store.search(search_term, limit=3)]
        result = await store.deliverability(ids, postcode)
        assert set(result) == set(ids)

    async def test_stock_covers_every_id(self, store: GroceryStore, search_term: str) -> None:
        ids = [p.id for p in await store.search(search_term, limit=3)]
        assert set(await store.stock(ids)) == set(ids)

    async def test_slots_are_well_formed(self, store: GroceryStore, postcode: str) -> None:
        for slot in await store.delivery_slots(postcode):
            assert slot.end > slot.start

    async def test_minimum_order_is_not_negative(self, store: GroceryStore) -> None:
        assert not (await store.minimum_order()).is_negative

    async def test_lists_are_addressed_by_id(self, store: GroceryStore, list_id: str) -> None:
        assert any(ref.id == list_id for ref in await store.lists())
        assert (await store.read_list(list_id)).id == list_id

    async def test_diff_list_is_pure(
        self, store: GroceryStore, list_id: str, search_term: str
    ) -> None:
        product = (await store.search(search_term, limit=1))[0]
        target = ShoppingList(
            id=list_id, lines=(ShoppingListLine(product_id=product.id, quantity=2),)
        )
        before = await store.read_list(list_id)
        assert await store.diff_list(list_id, target) == await store.diff_list(list_id, target)
        assert await store.read_list(list_id) == before

    async def test_apply_list_roundtrip(
        self, store: GroceryStore, list_id: str, search_term: str
    ) -> None:
        product = (await store.search(search_term, limit=1))[0]
        target = ShoppingList(
            id=list_id,
            lines=(
                ShoppingListLine(product_id=product.id, quantity=2),
                ShoppingListLine(text="free text item"),
            ),
        )
        original = await store.read_list(list_id)
        result = await store.apply_list(list_id, await store.diff_list(list_id, target))
        assert result.ok
        read = {k: v.quantity for k, v in (await store.read_list(list_id)).as_dict().items()}
        assert read == {k: v.quantity for k, v in target.as_dict().items()}
        assert (await store.diff_list(list_id, target)).is_empty
        await store.apply_list(list_id, await store.diff_list(list_id, original))


def carrot_incident_plan(product: Product, stray: Product) -> ShoppingPlan:
    """The incident of ADR-0016, in a store's own products: a quarter pack needed on the delivery
    day and a quarter pack later, two packs on the online basket, one more in store as a backup,
    and a product on the in-store list that no need asked for."""
    monday = date(2026, 10, 26)
    quarter = product.pack.to_base().scale(Decimal("0.25"))
    needs = (
        IngredientNeed(name="carrots", quantity=quarter, needed_on=monday),
        IngredientNeed(name="carrots", quantity=quarter, needed_on=monday + timedelta(days=3)),
    )

    def line(p: Product, channel: Channel, packs: int, **extra: object) -> ProductChoice:
        return ProductChoice(
            need_name=str(extra.pop("need_name", "carrots")),
            product=p,
            packs=packs,
            needed_on=monday,
            channel=channel,
            reason="contract",
            **extra,
        )

    return ShoppingPlan(
        slot=None,
        online=(line(product, Channel.ONLINE, 2, need_keys=(needs[1].key,)),),
        in_store=(
            line(product, Channel.STORE, 1, need_keys=(needs[0].key,), split_reason="backup"),
            line(stray, Channel.STORE, 1, need_name="stray"),
        ),
        needs=needs,
    )


def reconciliation_shape(findings: list[Finding]) -> list[tuple[FindingKind, str, Decimal | None]]:
    """What every adapter must agree on, whatever its product names and pack sizes."""
    return [(f.kind, f.need_name, f.excess_packs) for f in findings]


EXPECTED_INCIDENT_SHAPE = [
    (FindingKind.SURPLUS, "carrots", Decimal("2.5")),
    (FindingKind.CROSS_LIST, "carrots", None),
    (FindingKind.ORPHAN, "stray", None),
]


class ReconciliationContract:
    """A store's lists hold what the plan put there, so reconciling the plan and reconciling the
    lists as read back give the same findings, and every adapter gives the same ones as the
    in-memory fake (ADR-0016)."""

    @pytest.fixture
    def store(self) -> GroceryStore:
        raise NotImplementedError

    @pytest.fixture
    def search_term(self) -> str:
        """A search that finds at least two products."""
        raise NotImplementedError

    @pytest.fixture
    def online_list_id(self) -> str:
        raise NotImplementedError

    @pytest.fixture
    def in_store_list_id(self) -> str:
        raise NotImplementedError

    @pytest.fixture
    async def plan(self, store: GroceryStore, search_term: str) -> ShoppingPlan:
        hits = list(await store.search(search_term, limit=6))
        assert len(hits) >= 2, "the reconciliation contract needs two products"
        return carrot_incident_plan(hits[0], hits[1])

    async def test_incident_findings_are_the_same_for_every_adapter(
        self, plan: ShoppingPlan
    ) -> None:
        assert reconciliation_shape(reconcile(plan)) == EXPECTED_INCIDENT_SHAPE

    async def test_lists_read_back_reconcile_like_the_plan(
        self,
        store: GroceryStore,
        plan: ShoppingPlan,
        online_list_id: str,
        in_store_list_id: str,
    ) -> None:
        originals = [await store.read_list(i) for i in (online_list_id, in_store_list_id)]
        try:
            for list_id, lines in (
                (online_list_id, plan.online),
                (in_store_list_id, plan.in_store),
            ):
                target = shopping_list_from(list_id, lines)
                assert (await store.apply_list(list_id, await store.diff_list(list_id, target))).ok
            listed = await read_listed_plan(plan, store, online_list_id, in_store_list_id)
            assert reconcile(listed) == reconcile(plan)
        finally:
            for original in originals:
                await store.apply_list(original.id, await store.diff_list(original.id, original))

    async def test_a_product_added_by_hand_is_an_orphan(
        self,
        store: GroceryStore,
        plan: ShoppingPlan,
        online_list_id: str,
        in_store_list_id: str,
    ) -> None:
        originals = [await store.read_list(i) for i in (online_list_id, in_store_list_id)]
        stray = plan.in_store[1].product
        try:
            target = shopping_list_from(online_list_id, plan.online)
            target = target.model_copy(
                update={"lines": (*target.lines, ShoppingListLine(product_id=stray.id))}
            )
            await store.apply_list(online_list_id, await store.diff_list(online_list_id, target))
            await store.apply_list(
                in_store_list_id,
                await store.diff_list(
                    in_store_list_id, shopping_list_from(in_store_list_id, plan.in_store)
                ),
            )
            listed = await read_listed_plan(plan, store, online_list_id, in_store_list_id)
            orphans = [f for f in reconcile(listed) if f.kind == FindingKind.ORPHAN]
            assert {(f.id.split(":")[1], f.product_id) for f in orphans} == {
                ("online", stray.id),
                ("store", stray.id),
            }
        finally:
            for original in originals:
                await store.apply_list(original.id, await store.diff_list(original.id, original))


class PlannerProviderContract:
    @pytest.fixture
    def planner(self) -> PlannerProvider:
        raise NotImplementedError

    @pytest.fixture
    def context(self) -> PlanningContext:
        raise NotImplementedError

    async def test_is_a_planner(self, planner: PlannerProvider) -> None:
        assert isinstance(planner, PlannerProvider)

    async def test_proposal_stays_within_the_week(
        self, planner: PlannerProvider, context: PlanningContext
    ) -> None:
        proposal = await planner.propose(context)
        assert proposal.plan.week == context.week
        candidate_ids = {r.id.key for r in context.candidates}
        for meal in proposal.plan.meals:
            assert meal.date in context.week
            assert meal.servings > 0
            assert meal.recipe_id.key in candidate_ids


class NotifierContract:
    @pytest.fixture
    def notifier(self) -> Notifier:
        raise NotImplementedError

    async def test_notify_accepts_an_event(self, notifier: Notifier) -> None:
        await notifier.notify(PlanEvent(kind="test", title="t", message="m", actions=("approve",)))


def household_fixture_check(household: Household) -> None:
    assert household.members
