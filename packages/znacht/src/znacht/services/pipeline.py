"""The weekly run, wired to ports. Writes happen only in :func:`apply_week`."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import Field

from znacht.domain._base import Frozen
from znacht.domain.delivery import DeliverySlot
from znacht.domain.diff import ListDiff, PlanDiff
from znacht.domain.household import Household, SlotTemplate
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


def slots_from_templates(templates: tuple[SlotTemplate, ...], week: Week) -> list[DeliverySlot]:
    out: list[DeliverySlot] = []
    for t in templates:
        day = week.start + timedelta(days=t.weekday)
        sh, sm = (int(x) for x in t.start.split(":"))
        eh, em = (int(x) for x in t.end.split(":"))
        out.append(
            DeliverySlot(
                id=t.id,
                start=datetime(day.year, day.month, day.day, sh, sm),
                end=datetime(day.year, day.month, day.day, eh, em),
            )
        )
    return out


class PlanStatus(StrEnum):
    DRAFT = "draft"
    REVERTED = "reverted"
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


# What to search for per weekly rule tag. Sources that know tags use them; the others match words.
TAG_SEARCHES: dict[str, tuple[str, ...]] = {
    "fish": ("fish", "salmon"),
    "legumes": ("lentils", "chickpeas", "beans"),
    "red_meat": ("beef", "pork"),
    "poultry": ("chicken",),
    "vegetarian": ("vegetarian",),
}
GENERAL_SEARCHES: tuple[str, ...] = ("family dinner", "pasta", "rice")


def candidate_queries(household: Household, *, per_query: int) -> list[RecipeQuery]:
    """One targeted search per rule keyword plus general ones, within the weekday limit."""
    exclude = household.rules.banned_ingredients | household.allergies
    words: list[str] = []
    for tag in household.rules.min_tags:
        words.extend(TAG_SEARCHES.get(tag, (tag,)))
    words.extend(GENERAL_SEARCHES)
    return [
        RecipeQuery(
            text=word,
            exclude_ingredients=exclude,
            max_total_minutes=household.rules.max_total_minutes_weekday,
            limit=per_query,
        )
        for word in words
    ]


async def _plan(
    household: Household,
    week: Week,
    recipes: RecipeSource,
    planner: PlannerProvider,
    *,
    max_attempts: int,
    candidate_limit: int,
) -> tuple[MealPlan, dict[str, Recipe], list[Violation], str]:
    pool: dict[str, Recipe] = {}
    per_query = max(5, candidate_limit // 6)
    for query in candidate_queries(household, per_query=per_query):
        for recipe in await recipes.search(query):
            pool.setdefault(recipe.id.key, recipe)
    candidates = tuple(pool.values())[: max(candidate_limit, len(pool))]
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


_STOPWORDS = frozenset(
    {
        "about",
        "and",
        "approx",
        "boneless",
        "brown",
        "bunch",
        "can",
        "canned",
        "chopped",
        "clove",
        "cloves",
        "crushed",
        "dried",
        "extra",
        "fine",
        "fresh",
        "full",
        "green",
        "ground",
        "handful",
        "jar",
        "large",
        "medium",
        "of",
        "or",
        "packet",
        "pcs",
        "piece",
        "pieces",
        "plain",
        "raw",
        "red",
        "ripe",
        "salted",
        "skinless",
        "slice",
        "slices",
        "small",
        "sprig",
        "sprigs",
        "stalk",
        "stalks",
        "the",
        "tin",
        "tinned",
        "unsalted",
        "virgin",
        "white",
        "whole",
        "yellow",
    }
)


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for raw in text.lower().replace("-", " ").replace(",", " ").split():
        token = raw.strip("()'\".")
        if len(token) < 3 or token in _STOPWORDS:
            continue
        out.add(
            token[:-2]
            if token.endswith("es") and len(token) > 5
            else token[:-1]
            if token.endswith("s")
            else token
        )
    return out


_FORM_WORDS = frozenset(
    {
        "chip",
        "crisp",
        "soup",
        "sauce",
        "juice",
        "ale",
        "beer",
        "bottle",
        "bite",
        "snack",
        "candle",
        "carving",
        "costume",
        "toy",
        "seasoning",
        "spread",
        "dip",
        "syrup",
        "jam",
        "cake",
        "biscuit",
        "cookie",
        "candy",
        "drink",
        "smoothie",
        "pizza",
        "ready",
        "meal",
        "pickled",
        "marinated",
    }
)


def name_overlap(need_name: str, product_name: str) -> int:
    """How many meaningful words the product shares with the need. 0 means 'not this'."""
    return len(_tokens(need_name) & _tokens(product_name))


# Recipe vocabulary -> shop vocabulary. Tried in order when the full phrase finds nothing.
_SYNONYMS: tuple[tuple[str, str], ...] = (
    ("garlic cloves", "garlic"),
    ("garlic clove", "garlic"),
    ("capsicum", "peppers"),
    ("pouring (whipping) cream", "cream"),
    ("whipping cream", "cream"),
    ("pouring cream", "cream"),
    ("thickened cream", "cream"),
    ("ricotta salata", "ricotta"),
    ("eggplants", "aubergine"),
    ("eggplant", "aubergine"),
    ("eschalots", "shallots"),
    ("eschalot", "shallot"),
    ("tomato paste", "tomato purée"),
    ("cilantro", "coriander"),
    ("courgette", "zucchini"),
    ("aubergine", "eggplant"),
    ("spring onion", "spring onions"),
    ("scallion", "spring onions"),
    ("stock", "bouillon"),
)


def search_variants(need_name: str) -> list[str]:
    """The full phrase, then a synonym, then the phrase without adjectives, then single words."""
    name = need_name.lower().strip()
    out = [name]
    for src, dst in _SYNONYMS:
        if src in name:
            out.append(" ".join(name.replace(src, dst).replace("(", " ").replace(")", " ").split()))
    kept = [w for w in name.replace("-", " ").replace(",", " ").split() if w not in _STOPWORDS]
    if kept and " ".join(kept) != name:
        out.append(" ".join(kept))
    out.extend(w for w in sorted(kept, key=len, reverse=True) if len(w) > 3)
    seen: set[str] = set()
    unique: list[str] = []
    for v in out:
        if v not in seen:
            seen.add(v)
            unique.append(v)
    return unique


def relevance(need_name: str, product_name: str) -> float:
    """Shared words minus a penalty for words the need did not ask for. A product *form* the
    need did not mention (chips, soup, ale, bottle) disqualifies it."""
    need, prod = _tokens(need_name), _tokens(product_name)
    shared = need & prod
    if not shared:
        return 0.0
    extra = prod - need - {"migro", "classic", "budget", "bio", "organic"}
    if extra & _FORM_WORDS:
        return 0.0
    return len(shared) - 0.4 * len(extra)


def shortlist_for(need_name: str, candidates: list[Product]) -> list[Product]:
    scored = [(relevance(need_name, c.name), c) for c in candidates]
    best = max((r for r, _ in scored), default=0.0)
    if best <= 0:
        return []
    return [c for r, c in scored if r >= best - 0.5]


async def _choose_all(
    needs: list[IngredientNeed],
    household: Household,
    store: GroceryStore,
    channel: Channel,
    baselines: dict[str, Product],
    planner: PlannerProvider | None = None,
) -> tuple[list[ProductChoice], list[str]]:
    """Search, drop candidates that do not share a word with the need, optionally let the
    planner rank what is left, then apply the health-first optimiser."""
    choices: list[ProductChoice] = []
    unresolved: list[str] = []
    shortlist: dict[str, list[Product]] = {}
    for need in needs:
        relevant: list[Product] = []
        for variant in search_variants(need.name):
            candidates = list(await store.search(variant, category=need.category, limit=12))
            relevant = shortlist_for(variant, candidates)
            if relevant:
                break
        baseline = baselines.get(need.name)
        if baseline is not None and all(c.id != baseline.id for c in relevant):
            relevant.append(baseline)
        shortlist[need.name] = relevant
    ranked: dict[str, str | None] = {}
    rank = getattr(planner, "rank_products", None)
    if rank is not None and any(shortlist.values()):
        try:
            ranked = await rank({n.name: shortlist[n.name] for n in needs if shortlist[n.name]})
        except Exception:
            ranked = {}
    for need in needs:
        relevant = shortlist[need.name]
        picked = ranked.get(need.name)
        if need.name in ranked:
            relevant = [c for c in relevant if c.id == picked] if picked else []
        choice = choose_product(need, relevant, household, channel, baselines.get(need.name))
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
        slots = list(await store.delivery_slots(household.delivery.postcode))
        if not slots and household.delivery.slot_templates:
            slots = slots_from_templates(household.delivery.slot_templates, week)
            notes.append("store listed no delivery slots; using the household's slot templates")
        preferred = household.delivery.preferred_slot_id
        slot = next((s for s in slots if s.id == preferred), slots[0] if slots else None)
        if slot is None:
            notes.append("no delivery slot available; everything goes on the in-store list")

    # Staples the recipes assume (salt, oil, spices, stock) are not bought: they go on a
    # pantry-check list unless the pantry says they are missing (quantity 0).
    pantry = household.pantry.as_dict()
    pantry_check = sorted({n.name for n in needs if n.staple and n.name not in pantry})
    needs = [n for n in needs if not (n.staple and n.name not in pantry)]

    online_needs, store_needs = timing_split(needs, slot)
    online_needs, store_needs = merge_needs(online_needs), merge_needs(store_needs)

    baselines: dict[str, Product] = {}
    for name, pid in household.preferred_products.items():
        try:
            baselines[name] = await store.product(ProductId(pid))
        except LookupError:
            notes.append(f"preferred product {pid} for {name} no longer exists")

    online, unresolved_online = await _choose_all(
        online_needs, household, store, Channel.ONLINE, baselines, planner
    )
    in_store, unresolved_store = await _choose_all(
        store_needs, household, store, Channel.STORE, baselines, planner
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
        pantry_check=tuple(pantry_check),
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


async def revert_week(
    result: WeekResult, *, store: GroceryStore, sink: MealPlanSink, approved: bool
) -> WeekResult:
    """Undo an applied run: put back what apply removed and take out what it added."""
    if not approved:
        raise PermissionError("revert_week needs approved=True; nothing was written")
    if result.status != PlanStatus.APPLIED:
        raise ValueError(f"cannot revert a result in status {result.status}")
    notes = list(result.notes)
    if result.plan_diff is not None and not result.plan_diff.is_empty:
        undone = await sink.apply(result.plan_diff.inverse())
        notes.append(f"meal plan reverted: {undone.message or undone.applied}")
    for diff in (result.online_diff, result.in_store_diff):
        if diff is not None and not diff.is_empty:
            undone = await store.apply_list(diff.list_id, diff.inverse())
            notes.append(f"list {diff.list_id} reverted: {undone.message or undone.applied}")
    return result.model_copy(update={"status": PlanStatus.REVERTED, "notes": tuple(notes)})


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
