"""The engine's use cases. One household per engine instance; runs are persisted."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Any

from znacht.config import load_household
from znacht.domain.household import Household, Pantry, PantryItem
from znacht.domain.money import Money
from znacht.domain.plan import Meal, MealPlan, MealSlot, Week
from znacht.domain.quantity import Quantity
from znacht.domain.recipe import Recipe, RecipeId
from znacht.ports.notify import Notifier, PlanEvent
from znacht.services.checker import check_plan
from znacht.services.pipeline import (
    PlanStatus,
    WeekResult,
    apply_week,
    basket_summary,
    revert_week,
    run_week,
)
from znacht_engine.brief import WALK_ORDER, Brief, build_brief, lifetime, price_rows
from znacht_engine.config import EngineSettings
from znacht_engine.repo import Repo
from znacht_engine.timeline import (
    DEFAULT_DAYS,
    MAX_DAYS,
    WEEKDAYS,
    coverage,
    dinner_on,
    is_breakfast,
    pick_dinner,
    summary,
    week_label,
)
from znacht_engine.wiring import Adapters

log = logging.getLogger(__name__)

LIVE_READ_SECONDS = 180  # My Week and the store lists are re-read at most this often


def next_monday(today: date | None = None) -> date:
    today = today or date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


class ZnachtService:
    def __init__(
        self,
        settings: EngineSettings,
        repo: Repo,
        adapters: Adapters,
        notifier: Notifier | None = None,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.adapters = adapters
        self.notifier = notifier
        self._lock = asyncio.Lock()
        self._busy: str | None = None
        self._recipes: dict[str, Recipe] = {}
        self._my_week_cache: dict[date, tuple[float, MealPlan]] = {}
        self._lists_cache: tuple[float, dict[str, frozenset[str]]] | None = None

    # -- household with the engine's overlays ------------------------------------------------
    def household(self) -> Household:
        base = load_household(self.settings.household_path)
        pantry_overlay: dict[str, str] = self.repo.get("pantry.overlay", {})
        preferred_overlay: dict[str, str] = self.repo.get("preferred.overlay", {})
        pantry = dict(base.pantry.as_dict())
        for name, qty in pantry_overlay.items():
            if qty in ("", "0", None):
                pantry.pop(name, None)
            else:
                pantry[name] = Quantity.parse(qty)
        preferred = {**base.preferred_products, **preferred_overlay}
        return base.model_copy(
            update={
                "pantry": Pantry(
                    items=tuple(PantryItem(name=n, quantity=q) for n, q in sorted(pantry.items()))
                ),
                "preferred_products": preferred,
            }
        )

    @property
    def busy(self) -> str | None:
        return self._busy

    # -- use cases --
    async def plan_week(
        self,
        week_start: date | None = None,
        *,
        base_run: int | None = None,
        fixed_plan: MealPlan | None = None,
        channel_overrides: dict[str, str] | None = None,
        locked_dates: tuple[date, ...] | None = None,
    ) -> tuple[int, WeekResult]:
        """Plan a week. With ``base_run`` the new run inherits that run's candidate pool,
        locks and channel overrides (a swap, a move, or 'plan again')."""
        async with self._lock:
            self._busy = "planning"
            try:
                household = self.household()
                base = self.repo.get_run(base_run) if base_run is not None else None
                if base is not None and week_start is None:
                    week_start = base.week.start
                week = Week(start=week_start or next_monday())
                known = base.candidates if base is not None else ()
                overrides = dict(base.channel_overrides) if base is not None else {}
                if channel_overrides:
                    overrides.update(channel_overrides)
                locks = (
                    tuple(locked_dates)
                    if locked_dates is not None
                    else (base.locked_dates if base else ())
                )
                locked_meals = await self._locked_meals(week, locks, base)
                result = await run_week(
                    household,
                    week,
                    recipes=self.adapters.recipes,
                    store=self.adapters.store,
                    sink=self.adapters.sink,
                    planner=self.adapters.planner,
                    recent_meals=self.recent_meals(before=week),
                    locked_meals=locked_meals,
                    fixed_plan=fixed_plan,
                    known_candidates=known,
                    channel_overrides=overrides,
                )
                run_id = self.repo.save_run(result)
                self.repo.set("last_error", None)
                if base_run is not None:
                    self._carry_shopping_state(base_run, run_id)
                self.repo.record_prices(price_rows(result))
                await self._remember_recipes(result)
                await self._notify_plan(run_id, result)
                return run_id, result
            finally:
                self._busy = None

    async def apply(self, run_id: int | None = None) -> tuple[int, WeekResult]:
        async with self._lock:
            self._busy = "applying"
            try:
                rid, result = self._run(run_id)
                applied = await apply_week(
                    result, store=self.adapters.store, sink=self.adapters.sink, approved=True
                )
                self.repo.update_run(rid, applied)
                self.forget_live_reads()
                if applied.new_preferred:
                    overlay = self.repo.get("preferred.overlay", {})
                    overlay.update(applied.new_preferred)
                    self.repo.set("preferred.overlay", overlay)
                self.repo.record_applied(
                    applied.week.start.isoformat(),
                    str(applied.shopping.savings.amount),
                    str(applied.shopping.online_total.amount),
                )
                if self.notifier:
                    await self.notifier.notify(
                        PlanEvent(
                            kind="applied",
                            title="Znacht: plan sent",
                            message=(
                                "My Week and both lists are updated. Online basket "
                                f"{applied.shopping.online_total}. "
                                "Finish the order when you are ready."
                            ),
                            actions=("review",),
                            data={"url": self.notify_url(rid), "run_id": str(rid)},
                        )
                    )
                return rid, applied
            finally:
                self._busy = None

    def adapter_names(self) -> dict[str, str]:
        return {
            "recipes": getattr(self.adapters.recipes, "name", "?"),
            "store": getattr(self.adapters.store, "name", "?"),
            "sink": getattr(self.adapters.sink, "name", "?"),
            "planner": getattr(self.adapters.planner, "name", "?"),
        }

    def household_view(self) -> dict[str, Any]:
        h = self.household()
        return {
            "id": h.id,
            "name": h.name,
            "servings": h.servings,
            "needs_mild_food": h.needs_mild_food,
            "members": [
                {
                    "name": m.name,
                    "age_group": str(m.age_group),
                    "dislikes": sorted(m.dislikes),
                    "allergies": sorted(m.allergies),
                    "needs_mild_food": m.needs_mild_food,
                    "mild_food": m.mild_food,  # as written; edits carry it back unchanged
                }
                for m in h.members
            ],
            "rules": {
                "dinners_per_week": h.rules.dinners_per_week,
                "min_tags": h.rules.min_tags,
                "max_tags": h.rules.max_tags,
                "banned_ingredients": sorted(h.rules.banned_ingredients),
                "max_total_minutes_weekday": h.rules.max_total_minutes_weekday,
            },
            "health": {
                "rules": [r.text for r in h.health.rules],
                "markers": [m.model_dump(mode="json") for m in h.health.markers],
            },
            "pantry": [{"name": i.name, "quantity": str(i.quantity)} for i in h.pantry.items],
            "make_at_home": [m.dish for m in h.make_at_home],
            "delivery": {
                "postcode": h.delivery.postcode,
                "preferred_slot_id": h.delivery.preferred_slot_id,
            },
            "store_lists": {"online": h.store_lists.online, "in_store": h.store_lists.in_store}
            if h.store_lists
            else None,
            "preferred_products": h.preferred_products,
        }

    # -- app verbs --
    def alternatives(self, run_id: int, day: date) -> list[dict[str, Any]]:
        """Candidates that could replace the dinner on ``day`` and still keep the rules."""
        _, result = self._run(run_id)
        household = self.household()
        known = {r.id.key: r for r in result.candidates}
        for m in result.plan.meals:
            if m.recipe_id.key in self._recipes:
                known.setdefault(m.recipe_id.key, self._recipes[m.recipe_id.key])
        current = next((m for m in result.plan.meals if m.date == day), None)
        in_plan = {m.recipe_id.key for m in result.plan.meals}
        out: list[dict[str, Any]] = []
        seen_titles: set[str] = set()
        for recipe in result.candidates:
            # a swap must be a dinner, not a side or a basic: enough ingredients, unique title
            if recipe.id.key in in_plan or len(recipe.ingredients) < 4:
                continue
            if recipe.title.lower() in seen_titles:
                continue
            seen_titles.add(recipe.title.lower())
            trial_meals = (
                *(m for m in result.plan.meals if m.date != day),
                Meal(
                    date=day, slot=MealSlot.DINNER, recipe_id=recipe.id, servings=household.servings
                ),
            )
            violations = check_plan(MealPlan(week=result.week, meals=trial_meals), known, household)
            hard = [
                v
                for v in violations
                if v.code
                in ("banned_ingredient", "allergen", "not_mild", "too_long_weekday", "dislike")
            ]
            if hard:
                continue
            out.append(
                {
                    "recipe_id": recipe.id.key,
                    "title": recipe.title,
                    "minutes": recipe.total_minutes,
                    "tags": sorted(recipe.tags),
                    "spiciness": str(recipe.spiciness),
                    "keeps_rules": not violations,
                    "url": recipe.url,
                }
            )
        out.sort(key=lambda a: (not a["keeps_rules"], a["minutes"] or 999))
        if current is not None:
            out = [a for a in out if a["recipe_id"] != current.recipe_id.key]
        return out[:12]

    async def swap(self, run_id: int, day: date, recipe_key: str) -> tuple[int, WeekResult]:
        _, result = self._run(run_id)
        source, _, external = recipe_key.partition(":")
        household = self.household()
        meals = (
            *(m for m in result.plan.meals if m.date != day),
            Meal(
                date=day,
                slot=MealSlot.DINNER,
                recipe_id=RecipeId(source=source, external_id=external),
                servings=household.servings,
            ),
        )
        return await self.plan_week(
            base_run=run_id, fixed_plan=MealPlan(week=result.week, meals=meals)
        )

    async def set_lock(self, run_id: int, day: date, locked: bool) -> tuple[int, WeekResult]:
        rid, result = self._run(run_id)
        locks = set(result.locked_dates)
        if locked:
            locks.add(day)
        else:
            locks.discard(day)
        updated = result.model_copy(update={"locked_dates": tuple(sorted(locks))})
        self.repo.update_run(rid, updated)
        return rid, updated

    async def move(self, run_id: int, need_name: str, to: str) -> tuple[int, WeekResult]:
        _, result = self._run(run_id)
        return await self.plan_week(
            base_run=run_id, fixed_plan=result.plan, channel_overrides={need_name: to}
        )

    async def replan(self, run_id: int) -> tuple[int, WeekResult]:
        """Plan again for the same week, keeping locked dinners and the candidate pool."""
        return await self.plan_week(base_run=run_id)

    def view(self, run_id: int | None = None) -> dict[str, Any]:
        """Everything the app's Week and Groceries screens show, in one document."""
        rid, result = self._run(run_id)
        b = self.brief(rid)
        s = result.shopping
        lists = self.lists(rid)
        return {
            "run_id": rid,
            "status": str(result.status),
            "week": result.week.start.isoformat(),
            "week_label": b.week_label,
            "theme": b.theme,
            "chef_note": b.chef_note,
            "slot": b.slot_label,
            "dinners": [
                {
                    "date": d.date,
                    "weekday": d.weekday,
                    "title": d.title,
                    "recipe_id": d.recipe_id,
                    "minutes": d.minutes,
                    "tags": d.tags,
                    "note": d.note,
                    "cost_per_person": str(d.cost_per_person.amount) if d.cost_per_person else None,
                    "in_store_day": d.in_store_day,
                    "locked": date.fromisoformat(d.date) in result.locked_dates,
                    "url": self._recipes[d.recipe_id].url if d.recipe_id in self._recipes else None,
                }
                for d in b.dinners
            ],
            "money": {
                "online_subtotal": str(s.online_subtotal.amount),
                "deposit": str(s.deposit.amount),
                "online_total": str(s.online_total.amount),
                "minimum_order": str(s.minimum_order.amount),
                "meets_minimum": s.meets_minimum,
                "shortfall": str(s.shortfall.amount),
                "in_store_total": str(s.in_store_total.amount),
                "savings": str(s.savings.amount),
                "lifetime_savings": str(b.lifetime_savings.amount),
            },
            "online": [self._line(c, "online") for c in s.online],
            "in_store": [self._line(c, "store") for c in s.in_store],
            "free_text": list(s.free_text),
            "pantry_check": list(s.pantry_check),
            "swaps": [
                {
                    "need": x.need,
                    "chosen": x.chosen,
                    "reason": x.reason,
                    "kind": x.kind,
                    "delta": str(x.delta.amount) if x.delta else None,
                    "alternative": x.alternative,
                }
                for x in b.swaps
            ],
            "plan_removes": b.plan_removes,
            "violations": b.violations,
            "notes": b.notes,
            "todo": lists,
            "checkout_url": b.checkout_url,
            "busy": self._busy,
        }

    def _line(self, c: Any, where: str) -> dict[str, Any]:
        price = c.line_total()
        return {
            "need": c.need_name,
            "product_id": str(c.product.id),
            "name": c.product.name,
            "packs": c.packs,
            "pack": str(c.product.pack),
            "needed_on": c.needed_on.isoformat(),
            "price": str(price.amount),
            "reason": c.reason,
            "where": where,
            "movable": where == "store"
            and c.product.price_online is not None
            and c.deliverable is not False,
            "deliverable": c.deliverable,
            "flagged": c.flagged,
            "switched": c.switched,
            "url": c.product.url,
            "aisle": next(
                (name for name, cats in WALK_ORDER if c.product.category in cats), "Other"
            ),
        }

    async def revert(self, run_id: int) -> tuple[int, WeekResult]:
        """Undo an applied run on Cookidoo and the store. Explicit, like apply."""
        async with self._lock:
            self._busy = "reverting"
            try:
                rid, result = self._run(run_id)
                reverted = await revert_week(
                    result, store=self.adapters.store, sink=self.adapters.sink, approved=True
                )
                self.repo.update_run(rid, reverted)
                self.forget_live_reads()
                return rid, reverted
            finally:
                self._busy = None

    async def refresh(self) -> dict[str, Any]:
        """Re-read the store lists for the household's list IDs. Read-only."""
        household = self.household()
        out: dict[str, Any] = {}
        if household.store_lists:
            for kind, list_id in (
                ("online", household.store_lists.online),
                ("in_store", household.store_lists.in_store),
            ):
                try:
                    lst = await self.adapters.store.read_list(list_id)
                    out[kind] = [line.model_dump(mode="json") for line in lst.lines]
                except Exception as exc:
                    out[kind] = {"error": str(exc)}
        return out

    def update_pantry(self, items: dict[str, str]) -> dict[str, str]:
        overlay: dict[str, str] = self.repo.get("pantry.overlay", {})
        for name, qty in items.items():
            overlay[name.strip().lower()] = qty
        self.repo.set("pantry.overlay", overlay)
        return overlay

    # -- views --
    def _run(self, run_id: int | None) -> tuple[int, WeekResult]:
        if run_id is not None:
            result = self.repo.get_run(run_id)
            if result is None:
                raise LookupError(f"run {run_id} not found")
            return run_id, result
        latest = self.repo.latest_run(self.household().id)
        if latest is None:
            raise LookupError("no run yet; call plan_week first")
        return latest

    def status(self) -> dict[str, Any]:
        latest = self.repo.latest_run(self.household().id)
        today = date.today()
        last_error = self.repo.get("last_error")
        if latest is None:
            return {
                "plan_status": "idle",
                "busy": self._busy,
                "last_error": last_error,
                "run_id": None,
                "shopping_run_id": None,
                "adapters": self.adapter_names(),
                "lifetime_savings": "0.00",
            }
        rid, result = latest
        s = result.shopping
        todays = [m for m in result.plan.meals if m.date == today]
        return {
            "run_id": rid,
            "plan_status": str(result.status) if not self._busy else self._busy,
            "busy": self._busy,
            "last_error": last_error,
            "shopping_run_id": self.shopping_run_id(),
            "week": result.week.start.isoformat(),
            "theme": result.rationale.split(":", 1)[0] if ":" in result.rationale else None,
            "basket_total": str(s.online_total.amount),
            "basket_subtotal": str(s.online_subtotal.amount),
            "minimum_order": str(s.minimum_order.amount),
            "meets_minimum": s.meets_minimum,
            "shortfall": str(s.shortfall.amount),
            "next_delivery": s.slot.start.isoformat() if s.slot else None,
            "next_delivery_end": s.slot.end.isoformat() if s.slot else None,
            "in_store_items": len(s.in_store),
            "online_items": len(s.online),
            "switches": len(s.switches),
            "flags": len(s.flags),
            "savings": str(s.savings.amount),
            "lifetime_savings": str(lifetime(self.repo.ledger()).amount),
            "todays_dinner": self._title(todays[0].recipe_id.key) if todays else None,
            "violations": [str(v) for v in result.violations],
            "brief_url": self.brief_url(rid),
            "summary": {k: str(v) for k, v in basket_summary(s).items()},
            "adapters": self.adapter_names(),
        }

    def shopping_run_id(self, today: date | None = None) -> int | None:
        """The run whose groceries the household is shopping for: the applied run of this
        week, else the nearest applied week ahead, else the latest run. Planning next week
        must not hide the list you are standing in the shop with."""
        this = Week.containing(today or date.today()).start.isoformat()
        rows = self.repo.runs(self.household().id, limit=200)
        applied = sorted(
            (r for r in rows if r["status"] == str(PlanStatus.APPLIED) and r["week"] >= this),
            key=lambda r: (r["week"], -int(r["id"])),
        )
        if applied:
            return int(applied[0]["id"])
        return int(rows[0]["id"]) if rows else None

    def lists(self, run_id: int | None = None) -> dict[str, list[dict[str, Any]]]:
        rid, result = self._run(run_id)
        done: dict[str, bool] = self.repo.get(f"todo.done.{rid}", {})
        extra: list[str] = self.repo.get(f"todo.extra.{rid}", [])

        def items(choices: Any, kind: str) -> list[dict[str, Any]]:
            out = [
                {
                    "uid": f"{kind}:{c.product.id}",
                    "summary": f"{c.packs}× {c.product.name}",
                    "description": f"{c.need_name} · {c.line_total()} · {c.reason}",
                    "done": done.get(f"{kind}:{c.product.id}", False),
                }
                for c in choices
            ]
            if kind == "in_store":
                out += [
                    {
                        "uid": f"text:{t}",
                        "summary": t,
                        "description": "free text",
                        "done": done.get(f"text:{t}", False),
                    }
                    for t in (*result.shopping.free_text, *extra)
                ]
            return out

        return {
            "online": items(result.shopping.online, "online"),
            "in_store": items(result.shopping.in_store, "in_store"),
        }

    def _carry_shopping_state(self, base_run: int, run_id: int) -> None:
        """A swap or a move derives a new run; what was ticked off and what was added by hand
        on the base run stays with the shopping, not with the run id."""
        for key in ("todo.done", "todo.extra"):
            value = self.repo.get(f"{key}.{base_run}")
            if value:
                self.repo.set(f"{key}.{run_id}", value)

    def set_done(self, uid: str, done: bool, run_id: int | None = None) -> None:
        rid, _ = self._run(run_id)
        state = self.repo.get(f"todo.done.{rid}", {})
        state[uid] = done
        self.repo.set(f"todo.done.{rid}", state)

    def add_free_text(self, text: str, run_id: int | None = None) -> None:
        rid, _ = self._run(run_id)
        extra = self.repo.get(f"todo.extra.{rid}", [])
        if text not in extra:
            extra.append(text)
        self.repo.set(f"todo.extra.{rid}", extra)

    async def calendar(self) -> list[dict[str, Any]]:
        """Dinners for the HA calendar: what is in My Week (source run or manual) over the
        timeline horizon, plus proposals on days that have nothing yet, flagged as such. The
        latest run's week is always included so a proposal for a far week shows up."""
        today = date.today()
        start, end = today, today + timedelta(days=DEFAULT_DAYS - 1)
        latest = self.repo.latest_run(self.household().id)
        if latest is not None:
            start = min(start, latest[1].week.start)
            end = max(end, latest[1].week.end)
        tl = await self.timeline(start, (end - start).days + 1)
        out: list[dict[str, Any]] = []
        for day in tl["days"]:
            card = day["dinner"] or day["proposal"]
            cards = ([card] if card else []) + day["also"]
            for c in cards:
                out.append(
                    {
                        "date": day["date"],
                        "slot": "breakfast" if c["breakfast"] else "dinner",
                        "summary": c["title"],
                        "recipe_id": c["recipe_id"],
                        "servings": c["servings"],
                        "url": c["url"],
                        "note": c["note"],
                        "source": c["source"],
                        "proposed": c is card and day["dinner"] is None,
                    }
                )
        return out

    # -- the timeline (ADR-0011) --
    def forget_live_reads(self) -> None:
        """Drop cached My Week and list reads; called after every write."""
        self._my_week_cache.clear()
        self._lists_cache = None

    async def my_week(self, week: Week) -> MealPlan:
        """What is really in the sink for ``week``, re-read at most every few minutes."""
        hit = self._my_week_cache.get(week.start)
        if hit is not None and time.monotonic() - hit[0] < LIVE_READ_SECONDS:
            return hit[1]
        plan = await self.adapters.sink.read_week(week)
        self._my_week_cache[week.start] = (time.monotonic(), plan)
        return plan

    async def _locked_meals(
        self, week: Week, locks: tuple[date, ...], base: WeekResult | None
    ) -> tuple[Meal, ...]:
        """Meals to keep on the locked dates: My Week's dinner wins, the base run's fills in."""
        if not locks:
            return ()
        in_sink: dict[date, Meal] = {}
        try:
            current = await self.my_week(week)
        except Exception as exc:  # the sink is live; a read failure must not block planning
            log.warning("could not read My Week for %s: %s", week, exc)
        else:
            for d in sorted(locks):
                dinner, _ = await self._day_in_my_week(current, d)
                if dinner is not None:
                    in_sink[d] = dinner
        from_base = {m.date: m for m in (base.plan.dinners() if base else [])}
        return tuple(
            in_sink.get(d) or from_base[d] for d in sorted(locks) if d in in_sink or d in from_base
        )

    async def _list_members(self) -> dict[str, frozenset[str]]:
        """Product IDs currently on the household's two store lists (cached)."""
        if self._lists_cache and time.monotonic() - self._lists_cache[0] < LIVE_READ_SECONDS:
            return self._lists_cache[1]
        out: dict[str, frozenset[str]] = {}
        household = self.household()
        if household.store_lists:
            for kind, list_id in (
                ("online", household.store_lists.online),
                ("in_store", household.store_lists.in_store),
            ):
                try:
                    lst = await self.adapters.store.read_list(list_id)
                except Exception as exc:
                    log.warning("could not read list %s: %s", list_id, exc)
                    continue
                out[kind] = frozenset(
                    str(line.product_id) for line in lst.lines if line.product_id is not None
                )
        self._lists_cache = (time.monotonic(), out)
        return out

    def _runs_for_week(
        self, week: Week
    ) -> tuple[tuple[int, WeekResult] | None, tuple[int, WeekResult] | None]:
        """(latest applied run, run awaiting approval) for ``week``. The awaiting run is the
        newest run of the week when it still needs approval or input; an applied or reverted
        newest run means nothing is pending."""
        rows = [
            r
            for r in self.repo.runs(self.household().id, limit=200)
            if r["week"] == week.start.isoformat()
        ]
        applied = next((r for r in rows if r["status"] == str(PlanStatus.APPLIED)), None)
        awaiting = (
            rows[0]
            if rows and rows[0]["status"] in (PlanStatus.NEEDS_APPROVAL, PlanStatus.NEEDS_INPUT)
            else None
        )

        def load(row: dict[str, Any] | None) -> tuple[int, WeekResult] | None:
            if row is None:
                return None
            result = self.repo.get_run(int(row["id"]))
            return (int(row["id"]), result) if result is not None else None

        return load(applied), load(awaiting)

    async def _recipe(self, rid: RecipeId) -> Recipe | None:
        if rid.key in self._recipes:
            return self._recipes[rid.key]
        try:
            recipe = await self.adapters.recipes.get(rid)
        except Exception:
            return None
        self._recipes[rid.key] = recipe
        return recipe

    async def _card(self, meal: Meal, source: int | str) -> dict[str, Any]:
        recipe = await self._recipe(meal.recipe_id)
        return {
            "title": recipe.title if recipe else meal.recipe_id.external_id,
            "recipe_id": meal.recipe_id.key,
            "source": source,
            "servings": meal.servings,
            "minutes": recipe.total_minutes if recipe else None,
            "tags": sorted(recipe.tags) if recipe else [],
            "url": recipe.url if recipe else None,
            "note": meal.note,
            "breakfast": is_breakfast(meal, recipe),
        }

    async def _day_in_my_week(self, mine: MealPlan, day: date) -> tuple[Meal | None, list[Meal]]:
        """What My Week holds on ``day``: the dinner (breakfasts skipped) and the other recipes."""
        meals = mine.on(day)
        recipes = {m.recipe_id.key: await self._recipe(m.recipe_id) for m in meals}
        return pick_dinner(meals, lambda m: recipes[m.recipe_id.key])

    async def timeline(self, from_: date | None = None, days: int = DEFAULT_DAYS) -> dict[str, Any]:
        """One record per day from ``from_`` (today) for ``days``: what My Week says, what a
        run proposes, and whether the food is arriving, listed or missing (ADR-0011)."""
        today = date.today()
        start = from_ or today
        days = max(1, min(days, MAX_DAYS))
        dates = [start + timedelta(days=i) for i in range(days)]
        members = await self._list_members()
        weeks: dict[date, dict[str, Any]] = {}
        for ws in sorted({Week.containing(d).start for d in dates}):
            week = Week(start=ws)
            applied, awaiting = self._runs_for_week(week)
            ok = True
            try:
                mine = await self.my_week(week)
            except Exception as exc:
                log.warning("could not read My Week for %s: %s", week, exc)
                ok = False
                mine = applied[1].plan if applied else MealPlan(week=week)
            weeks[ws] = {
                "week": week,
                "applied": applied,
                "awaiting": awaiting,
                "mine": mine,
                "ok": ok,
            }

        known_before = len(self._recipes)
        records: list[dict[str, Any]] = []
        for d in dates:
            w = weeks[Week.containing(d).start]
            applied, awaiting, mine = w["applied"], w["awaiting"], w["mine"]
            in_sink, rest = await self._day_in_my_week(mine, d)
            in_applied = dinner_on(applied[1].plan.meals, d) if applied else None
            in_awaiting = dinner_on(awaiting[1].plan.meals, d) if awaiting else None
            dinner = proposal = None
            # the applied run's lists cover a dinner its plan contains; the dinner is *from*
            # the run only when the run added it to My Week (a locked or pre-existing dinner
            # stays yours)
            from_applied = (
                applied is not None
                and in_sink is not None
                and in_applied is not None
                and in_applied.recipe_id == in_sink.recipe_id
            )
            if in_sink is not None:
                added = applied is not None and (
                    applied[1].plan_diff is None or in_sink in applied[1].plan_diff.add
                )
                dinner = await self._card(
                    in_sink, applied[0] if from_applied and added and applied else "manual"
                )
            if (
                in_awaiting is not None
                and awaiting is not None
                and (in_sink is None or in_awaiting.recipe_id != in_sink.recipe_id)
            ):
                proposal = await self._card(in_awaiting, awaiting[0])
            if d < today:
                state = "past"
            elif dinner is not None:
                state = "planned"
            elif proposal is not None:
                state = "proposed"
            else:
                state = "empty"
            # the run the swap sheet acts on: the applied run that put the dinner there, else
            # the run awaiting approval (a swap on it is another proposal), else nothing
            act = applied if from_applied and applied else awaiting if proposal else None
            records.append(
                {
                    "date": d.isoformat(),
                    "weekday": WEEKDAYS[d.weekday()],
                    "week": w["week"].start.isoformat(),
                    "state": state,
                    "dinner": dinner,
                    "also": [await self._card(m, "manual") for m in rest],
                    "proposal": proposal,
                    "groceries": coverage(
                        d,
                        applied=applied[1] if applied else None,
                        from_applied=from_applied,
                        proposal=awaiting[1] if awaiting and proposal else None,
                        list_members=members,
                        today=today,
                    ),
                    "run_id": act[0] if act else None,
                    "locked": bool(act and d in act[1].locked_dates),
                    "my_week_ok": w["ok"],
                }
            )
        if len(self._recipes) != known_before:
            self.repo.set(
                "recipes.cache", {k: v.model_dump(mode="json") for k, v in self._recipes.items()}
            )

        week_records: list[dict[str, Any]] = []
        for ws, w in weeks.items():
            mine_days = [r for r in records if r["week"] == ws.isoformat()]
            awaiting_id = w["awaiting"][0] if w["awaiting"] else None
            week_records.append(
                {
                    "week": ws.isoformat(),
                    "label": week_label(w["week"], today),
                    "applied_run_id": w["applied"][0] if w["applied"] else None,
                    "awaiting_run_id": awaiting_id,
                    "awaiting_status": str(w["awaiting"][1].status) if w["awaiting"] else None,
                    "my_week_ok": w["ok"],
                    # what "Plan the gaps" locks: every date of the week with a dinner in My Week
                    "locked_dates": [
                        d.isoformat()
                        for d in w["week"].days()
                        if (await self._day_in_my_week(w["mine"], d))[0] is not None
                    ],
                    "summary": summary(mine_days, awaiting_run_id=awaiting_id),
                }
            )
        return {
            "from": start.isoformat(),
            "horizon": days,
            "today": today.isoformat(),
            "weeks": week_records,
            "days": records,
            "unplanned_dates": [r["date"] for r in records if r["state"] in ("empty", "proposed")],
            "empty_dates": [r["date"] for r in records if r["state"] == "empty"],
            "proposed_dates": [r["date"] for r in records if r["state"] == "proposed"],
            "busy": self._busy,
        }

    def brief(self, run_id: int | None = None) -> Brief:
        rid, result = self._run(run_id)
        checkout = self.settings.extra.get("checkout_url") or (
            "https://www.migros.ch/en?context=ecommerce"
            if self.settings.store == "migros"
            else None
        )
        return build_brief(
            rid,
            result,
            self._recipes,
            lifetime_savings=lifetime(self.repo.ledger()),
            checkout_url=checkout,
        )

    def brief_url(self, run_id: int) -> str:
        token = f"?token={self.settings.api_token}" if self.settings.api_token else ""
        return f"{self.settings.public_url}/brief/{run_id}{token}"

    def notify_url(self, run_id: int) -> str:
        """Where a notification opens: the Brief, or the add-on's panel inside Home Assistant."""
        return self.settings.notify_link or self.brief_url(run_id)

    def recent_meals(self, *, before: Week, weeks: int = 4) -> tuple[str, ...]:
        """Dinner titles from applied (or latest) runs of the previous weeks, newest first."""
        titles: list[str] = []
        seen_weeks: set[str] = set()
        for row in self.repo.runs(self.household().id, limit=40):
            if row["week"] >= before.start.isoformat() or row["week"] in seen_weeks:
                continue
            if row["status"] not in ("applied", "needs_approval", "reverted"):
                continue
            result = self.repo.get_run(int(row["id"]))
            if result is None:
                continue
            seen_weeks.add(row["week"])
            titles.extend(self._title(m.recipe_id.key) for m in result.plan.meals)
            if len(seen_weeks) >= weeks:
                break
        return tuple(titles)

    def _title(self, key: str) -> str:
        recipe = self._recipes.get(key)
        return recipe.title if recipe is not None else key.split(":", 1)[-1]

    # -- helpers --
    async def _remember_recipes(self, result: WeekResult) -> None:
        for rid in result.plan.recipe_ids():
            if rid.key not in self._recipes:
                try:
                    self._recipes[rid.key] = await self.adapters.recipes.get(rid)
                except LookupError:
                    continue
        self.repo.set(
            "recipes.cache", {k: v.model_dump(mode="json") for k, v in self._recipes.items()}
        )

    def load_recipe_cache(self) -> None:
        cached: dict[str, Any] = self.repo.get("recipes.cache", {})
        for key, data in cached.items():
            try:
                self._recipes[key] = Recipe.model_validate(data)
            except ValueError:
                continue

    async def _notify_plan(self, run_id: int, result: WeekResult) -> None:
        if not self.notifier:
            return
        s = result.shopping
        if result.status == PlanStatus.NEEDS_APPROVAL:
            theme = result.rationale.split(":", 1)[0] if ":" in result.rationale else "Plan ready"
            saved = (
                f"{len(s.switches)} swap{'s' if len(s.switches) != 1 else ''} save {s.savings}"
                if s.switches
                else "no swaps"
            )
            flags = f", {len(s.flags)} to look at" if s.flags else ""
            minimum = "" if s.meets_minimum else f" Basket is {s.shortfall} short of the minimum."
            message = (
                f"{theme}. Online {s.online_total}, store run {len(s.in_store)} items. "
                f"{saved}{flags}.{minimum}"
            )
            await self.notifier.notify(
                PlanEvent(
                    kind="plan_ready",
                    title="Znacht: plan ready",
                    message=message,
                    actions=("approve", "review"),
                    data={"url": self.notify_url(run_id), "run_id": str(run_id)},
                )
            )
        else:
            await self.notifier.notify(
                PlanEvent(
                    kind="needs_input",
                    title="Znacht needs a hand",
                    message="; ".join(str(v) for v in result.violations[:3])
                    or "The plan could not be completed.",
                    actions=("review",),
                    data={"url": self.notify_url(run_id), "run_id": str(run_id)},
                )
            )


def money(value: str) -> Money:
    return Money.chf(value)
