"""The weekly run, wired to ports. Writes happen only in :func:`apply_week`."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from znacht.domain._base import Frozen
from znacht.domain.delivery import DeliverySlot
from znacht.domain.diff import ListDiff, PlanDiff
from znacht.domain.household import Household
from znacht.domain.money import Money
from znacht.domain.needs import IngredientNeed
from znacht.domain.plan import MealPlan, Week
from znacht.domain.product import Channel, Product, ProductId, StockStatus
from znacht.domain.recipe import Recipe
from znacht.domain.shopping import MinimumOrderReport, ProductChoice, ShoppingPlan
from znacht.domain.violations import Violation
from znacht.ports.planner import PlannerProvider, PlanningContext
from znacht.ports.recipes import RecipeQuery, RecipeSource
from znacht.ports.sinks import MealPlanSink
from znacht.ports.stores import GroceryStore
from znacht.services.checker import check_plan
from znacht.services.lists import shopping_list_from
from znacht.services.minimum_order import ensure_minimum_order
from znacht.services.needs import explode_needs, merge_needs
from znacht.services.optimiser import choose_product
from znacht.services.split import timing_split


class PlanStatus(StrEnum):
    DRAFT = "draft"
    NEEDS_INPUT = "needs_input"
    NEEDS_APPROVAL = "needs_approval"
    APPLIED = "applied"
    ERROR = "error"


class WeekResult(Frozen):
    status: PlanStatus
    household_id: str
    week: Week
    plan: MealPlan
    violations: tuple[Violation, ...] = ()
    needs: tuple[IngredientNeed, ...] = ()
    shopping: ShoppingPlan
    minimum_order: MinimumOrderReport = MinimumOrderReport()
    plan_diff: PlanDiff | None = None
    online_diff: ListDiff | None = None
    in_store_diff: ListDiff | None = None
    new_preferred: dict[str, str] = Field(default_factory=dict)
    notes: tuple[str, ...] = ()
    rationale: str = ""


async def _plan(
    household: Household,
    week: Week,
    recipes: RecipeSource,
    planner: PlannerProvider,
    *,
    max_attempts: int,
    candidate_limit: int,
) -> tuple[MealPlan, dict[str, Recipe], list[Violation], str]:
    query = RecipeQuery(
        exclude_ingredients=household.rules.banned_ingredients | household.allergies,
        max_total_minutes=None,
        limit=candidate_limit,
    )
    candidates = tuple(await recipes.search(query))
    known = {r.id.key: r for r in candidates}
    violations: list[Violation] = []
    plan = MealPlan(week=week)
    rationale = ""
    for _ in range(max_attempts):
        context = PlanningContext(
            household=household,
            week=week,
            candidates=candidates,
            violations=tuple(violations),
            previous=plan if plan.meals else None,
        )
        proposal = await planner.propose(context)
        plan, rationale = proposal.plan, proposal.rationale
        for rid in plan.recipe_ids():
            if rid.key not in known:
                known[rid.key] = await recipes.get(rid)
        violations = check_plan(plan, known, household)
        if not violations:
            break
    return plan, known, violations, rationale


async def _choose_all(
    needs: list[IngredientNeed],
    household: Household,
    store: GroceryStore,
    channel: Channel,
    baselines: dict[str, Product],
) -> tuple[list[ProductChoice], list[str]]:
    choices: list[ProductChoice] = []
    unresolved: list[str] = []
    for need in needs:
        candidates = list(await store.search(need.name, category=need.category, limit=6))
        if not candidates:
            candidates = list(await store.search(need.name, limit=6))
        baseline = baselines.get(need.name)
        choice = choose_product(need, candidates, household, channel, baseline)
        if choice is None:
            unresolved.append(need.name)
        else:
            choices.append(choice)
    return choices, unresolved


async def run_week(
    household: Household,
    week: Week,
    *,
    recipes: RecipeSource,
    store: GroceryStore,
    sink: MealPlanSink,
    planner: PlannerProvider,
    slot: DeliverySlot | None = None,
    max_attempts: int = 3,
    candidate_limit: int = 50,
) -> WeekResult:
    """Plan, check, explode, split, optimise, top up, diff. No writes."""
    notes: list[str] = []
    plan, known, violations, rationale = await _plan(
        household,
        week,
        recipes,
        planner,
        max_attempts=max_attempts,
        candidate_limit=candidate_limit,
    )
    minimum = await store.minimum_order()
    empty = ShoppingPlan(slot=slot, minimum_order=minimum)
    if violations:
        return WeekResult(
            status=PlanStatus.NEEDS_INPUT,
            household_id=household.id,
            week=week,
            plan=plan,
            violations=tuple(violations),
            shopping=empty,
            notes=("plan violates the rules; nothing was split or priced",),
            rationale=rationale,
        )

    needs = explode_needs(plan, known, household)

    if slot is None:
        slots = await store.delivery_slots(household.delivery.postcode)
        preferred = household.delivery.preferred_slot_id
        slot = next((s for s in slots if s.id == preferred), slots[0] if slots else None)
        if slot is None:
            notes.append("no delivery slot available; everything goes on the in-store list")

    online_needs, store_needs = timing_split(needs, slot)
    online_needs, store_needs = merge_needs(online_needs), merge_needs(store_needs)

    baselines: dict[str, Product] = {}
    for name, pid in household.preferred_products.items():
        try:
            baselines[name] = await store.product(ProductId(pid))
        except LookupError:
            notes.append(f"preferred product {pid} for {name} no longer exists")

    online, unresolved_online = await _choose_all(
        online_needs, household, store, Channel.ONLINE, baselines
    )
    in_store, unresolved_store = await _choose_all(
        store_needs, household, store, Channel.STORE, baselines
    )
    free_text = list(household.free_text_items) + [
        f"{n} (no catalogue match)" for n in unresolved_online + unresolved_store
    ]

    # Deliverability per product and postcode: non-deliverable lines go in-store.
    if online:
        deliverable = await store.deliverability(
            [c.product.id for c in online], household.delivery.postcode
        )
        kept: list[ProductChoice] = []
        for c in online:
            info = deliverable.get(c.product.id)
            if info is not None and not info.deliverable:
                reason = info.reason or "not deliverable to this address"
                if c.product.price_store is not None:
                    in_store.append(
                        c.model_copy(
                            update={
                                "channel": Channel.STORE,
                                "deliverable": False,
                                "reason": f"{c.reason}; {reason}",
                            }
                        )
                    )
                else:
                    free_text.append(f"{c.need_name} (not deliverable, no store price)")
            else:
                kept.append(c.model_copy(update={"deliverable": True}))
        online = kept

    # Stock: after every switch, re-check availability and revert if needed.
    if online:
        stock = await store.stock([c.product.id for c in online])
        rechecked: list[ProductChoice] = []
        for c in online:
            if stock.get(c.product.id, StockStatus.UNKNOWN) != StockStatus.OUT:
                rechecked.append(c)
                continue
            baseline = baselines.get(c.need_name)
            if c.switched and baseline is not None and baseline.price_online is not None:
                need = next(n for n in online_needs if n.name == c.need_name)
                reverted = choose_product(need, [baseline], household, Channel.ONLINE, baseline)
                if reverted is not None:
                    rechecked.append(
                        reverted.model_copy(
                            update={
                                "deliverable": True,
                                "reason": f"reverted: {c.product.name} is out of stock online",
                            }
                        )
                    )
                    continue
            if c.product.price_store is not None:
                in_store.append(
                    c.model_copy(
                        update={
                            "channel": Channel.STORE,
                            "reason": f"{c.reason}; out of stock online",
                        }
                    )
                )
            else:
                free_text.append(f"{c.need_name} (out of stock online)")
        online = rechecked

    # Household preference: some categories, or clearly cheaper in-store items, go in-store
    # but stay movable so the minimum-order step can pull them back.
    policy = household.store_policy
    if online and slot is not None:
        kept = []
        for c in online:
            store_price = c.product.price(Channel.STORE)
            cheaper = (
                policy.prefer_store_when_cheaper_by is not None
                and store_price is not None
                and c.line_total(Channel.STORE) + policy.prefer_store_when_cheaper_by
                <= c.line_total(Channel.ONLINE)
            )
            prefer = (
                c.product.category in policy.prefer_store_categories and store_price is not None
            )
            if cheaper or prefer:
                why = "cheaper in store" if cheaper else "household buys this category in store"
                in_store.append(
                    c.model_copy(
                        update={
                            "channel": Channel.STORE,
                            "movable": True,
                            "reason": f"{c.reason}; {why}",
                        }
                    )
                )
            else:
                kept.append(c)
        online = kept

    shopping = ShoppingPlan(
        slot=slot,
        online=tuple(online),
        in_store=tuple(in_store),
        free_text=tuple(free_text),
        minimum_order=minimum,
        freezer_box_deposit=policy.freezer_box_deposit,
    )
    shopping, min_report = ensure_minimum_order(shopping)
    if min_report.ask_household is not None:
        notes.append(
            f"online basket is {min_report.ask_household} short of the minimum; "
            "ask the household for items it needs rather than padding with staples"
        )

    plan_diff = await sink.diff(plan)
    online_diff = in_store_diff = None
    if household.store_lists is not None:
        online_diff = await store.diff_list(
            household.store_lists.online,
            shopping_list_from(household.store_lists.online, shopping.online),
        )
        in_store_diff = await store.diff_list(
            household.store_lists.in_store,
            shopping_list_from(
                household.store_lists.in_store, shopping.in_store, shopping.free_text
            ),
        )
    else:
        notes.append("no store list IDs configured; list diffs skipped")

    new_preferred = {c.need_name: str(c.product.id) for c in shopping.switches}
    return WeekResult(
        status=PlanStatus.NEEDS_APPROVAL,
        household_id=household.id,
        week=week,
        plan=plan,
        needs=tuple(needs),
        shopping=shopping,
        minimum_order=min_report,
        plan_diff=plan_diff,
        online_diff=online_diff,
        in_store_diff=in_store_diff,
        new_preferred=new_preferred,
        notes=tuple(notes),
        rationale=rationale,
    )


async def apply_week(
    result: WeekResult, *, store: GroceryStore, sink: MealPlanSink, approved: bool
) -> WeekResult:
    """Write the diffs. Requires a result in ``needs_approval`` and an explicit approval."""
    if not approved:
        raise PermissionError("apply_week needs approved=True; nothing was written")
    if result.status != PlanStatus.NEEDS_APPROVAL:
        raise ValueError(f"cannot apply a result in status {result.status}")
    notes = list(result.notes)
    if result.plan_diff is not None and not result.plan_diff.is_empty:
        applied = await sink.apply(result.plan_diff)
        notes.append(f"meal plan: {applied.message or applied.applied}")
    for diff in (result.online_diff, result.in_store_diff):
        if diff is not None and not diff.is_empty:
            applied = await store.apply_list(diff.list_id, diff)
            notes.append(f"list {diff.list_id}: {applied.message or applied.applied}")
    return result.model_copy(update={"status": PlanStatus.APPLIED, "notes": tuple(notes)})


def basket_summary(shopping: ShoppingPlan) -> dict[str, Money | int | bool]:
    return {
        "online_lines": len(shopping.online),
        "online_subtotal": shopping.online_subtotal,
        "deposit": shopping.deposit,
        "online_total": shopping.online_total,
        "minimum_order": shopping.minimum_order,
        "meets_minimum": shopping.meets_minimum,
        "in_store_lines": len(shopping.in_store),
        "in_store_total": shopping.in_store_total,
        "switches": len(shopping.switches),
        "flags": len(shopping.flags),
        "savings": shopping.savings,
    }
