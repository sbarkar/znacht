"""The engine's use cases. One household per engine instance; runs are persisted."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Any

from znacht.config import load_household
from znacht.domain.diff import PlanDiff, ShoppingList, diff_lists
from znacht.domain.household import Household, Pantry, PantryItem
from znacht.domain.money import Money
from znacht.domain.plan import Meal, MealPlan, MealSlot, Week
from znacht.domain.quantity import Quantity
from znacht.domain.recipe import Recipe, RecipeId
from znacht.ports.notify import Notifier, PlanEvent
from znacht.ports.recipes import RecipeQuery
from znacht.services.checker import check_plan
from znacht.services.lists import shopping_list_from
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
from znacht_engine.edits import (
    EDIT_KINDS,
    OrderedLock,
    StaleEdit,
    diff_keys,
    edit_changes,
    grocery_meals,
    lock_reason,
    rebase_list,
    suggested_order_dates,
    touched_dates,
)
from znacht_engine.household_edit import EXAMPLE_HOUSEHOLD_ID, write_new_household
from znacht_engine.repo import Repo
from znacht_engine.timeline import (
    DEFAULT_DAYS,
    MAX_DAYS,
    WEEKDAYS,
    coverage,
    dinner_on,
    is_breakfast,
    ordered_coverage,
    pick_dinner,
    summary,
    week_label,
)
from znacht_engine.wiring import Adapters

log = logging.getLogger(__name__)

LIVE_READ_SECONDS = 180  # My Week and the store lists are re-read at most this often
HARD_RULES = ("banned_ingredient", "allergen", "not_mild", "too_long_weekday", "dislike")


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
        """Write an approved run (a proposal or an edit). Refused when it touches an ordered day
        or when My Week changed since the run was made (ADR-0014)."""
        async with self._lock:
            self._busy = "applying"
            try:
                rid, result = self._run(run_id)
                edit = self.edit_meta(rid)
                self.refuse_if_ordered(touched_dates(result.plan_diff))
                if result.status == PlanStatus.NEEDS_APPROVAL:
                    if edit is not None:
                        await self._check_edit_fresh(edit, result.week)
                    else:
                        await self._check_proposal_fresh(rid, result)
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
                if edit is not None and edit.get("base_run") is not None:
                    self._carry_shopping_state(int(edit["base_run"]), rid)
                if self.notifier and edit is None:
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

    # -- first setup and connections (ADR-0013) -----------------------------------------------
    def setup_needed(self) -> bool:
        """True while the household is still the shipped example (or missing)."""
        path = self.settings.household_path
        if not path.exists():
            return True
        try:
            return load_household(path).id == EXAMPLE_HOUSEHOLD_ID
        except ValueError:
            return False  # a hand-written file with a mistake: the household fixes it, not a wizard

    async def connections(self) -> dict[str, dict[str, Any]]:
        """Each connection, whether it works now and why not. Cheap: no planning, no LLM call."""
        names = self.adapter_names()
        problems = self.adapters.problems
        out: dict[str, dict[str, Any]] = {}
        for role, key in (("recipes", "cookidoo"), ("store", "migros"), ("planner", "anthropic")):
            name = names[role]
            entry: dict[str, Any] = {"name": name, "ok": True, "detail": None}
            if key in problems and name == key:
                entry.update(ok=False, detail=problems[key])
            elif role == "store" and name == "migros":
                try:
                    await self.adapters.store.lists()
                except Exception as exc:
                    entry.update(ok=False, detail=f"Migros login failed: {exc}")
            out[role] = entry
        out["sink"] = {
            "name": names["sink"],
            "ok": "cookidoo" not in problems or names["sink"] != "cookidoo",
            "detail": problems.get("cookidoo") if names["sink"] == "cookidoo" else None,
        }
        return out

    async def store_lists(self) -> list[dict[str, str]]:
        """The store account's shopping lists, for picking the online and in-store list."""
        lists = getattr(self.adapters.store, "lists", None)
        if lists is None:
            raise LookupError("this store has no lists")
        return [{"id": ref.id, "name": ref.name} for ref in await lists()]

    def setup(self, answers: dict[str, Any]) -> dict[str, Any]:
        """Write a fresh household from the Welcome wizard; keep the example next to it."""
        path = self.settings.household_path
        previous = path.read_text(encoding="utf-8") if path.exists() else None
        was_example = self.setup_needed()
        write_new_household(path, answers)  # validates first; the old file stays on failure
        if previous is not None and was_example:
            path.with_name("household.example.yaml").write_text(previous, encoding="utf-8")
        return self.household_view()

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
                "slots": [
                    {"id": t.id, "weekday": t.weekday, "start": t.start, "end": t.end}
                    for t in h.delivery.slot_templates
                ],
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
                self.refuse_if_ordered(touched_dates(result.plan_diff))
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
        latest = self._latest()
        if latest is None:
            raise LookupError("no run yet; call plan_week first")
        return latest

    def _latest(self) -> tuple[int, WeekResult] | None:
        """The newest run, skipping edit previews that were never confirmed."""
        for row in self.repo.runs(self.household().id, limit=50):
            if self.is_open_edit(int(row["id"]), row["status"]):
                continue
            result = self.repo.get_run(int(row["id"]))
            if result is not None:
                return int(row["id"]), result
        return None

    def status(self) -> dict[str, Any]:
        latest = self._latest()
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
        latest = self._latest()
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
                        "ordered": day["ordered"],
                    }
                )
        return out

    # -- editing the schedule and the order lock (ADR-0014) ---------------------------------
    def edit_meta(self, run_id: int) -> dict[str, Any] | None:
        meta: dict[str, Any] | None = self.repo.get(f"edit.{run_id}")
        return meta

    def is_open_edit(self, run_id: int, status: str) -> bool:
        """An edit preview that was never confirmed (or was discarded): not a run to show."""
        return status not in (PlanStatus.APPLIED, PlanStatus.REVERTED) and bool(
            self.edit_meta(run_id)
        )

    def ordered_dates(self) -> dict[date, dict[str, Any]]:
        """Each day covered by a recorded order, with that order (the newest wins)."""
        out: dict[date, dict[str, Any]] = {}
        for order in self.repo.orders():
            for d in order["dates"]:
                out[date.fromisoformat(d)] = order
        return out

    def refuse_if_ordered(self, dates: set[date] | list[date]) -> None:
        orders = self.ordered_dates()
        hit = sorted(d for d in dates if d in orders)
        if hit:
            names = ", ".join(f"{WEEKDAYS[d.weekday()]} {d.day}" for d in hit)
            raise OrderedLock(f"{names}: {lock_reason(orders[hit[0]])}")

    def orders_view(self) -> list[dict[str, Any]]:
        return [{**o, "lock_reason": lock_reason(o)} for o in self.repo.orders()]

    def order_for_run(self, run_id: int) -> dict[str, Any]:
        """What the Groceries screen offers for "I placed the order": the run's days, the ones
        an order would cover, and the order already recorded for the run, if any."""
        rid, result = self._run(run_id)
        today = date.today()
        recorded = next((o for o in self.orders_view() if o["run_id"] == rid), None)
        return {
            "run_id": rid,
            "order": recorded,
            "suggested": [d.isoformat() for d in suggested_order_dates(result, today)],
            "days": [
                {
                    "date": m.date.isoformat(),
                    "weekday": WEEKDAYS[m.date.weekday()],
                    "title": self._title(m.recipe_id.key),
                }
                for m in result.plan.dinners()
                if m.date >= today
            ],
        }

    def mark_ordered(self, run_id: int | None, dates: list[date] | None = None) -> dict[str, Any]:
        """Record that the household placed the order for ``run_id``. Writes only the engine's
        database: Znacht never orders (tests/safety)."""
        rid, result = self._run(run_id)
        if result.status != PlanStatus.APPLIED:
            raise ValueError("only groceries that were sent to your lists can be ordered")
        days = sorted(set(dates)) if dates else suggested_order_dates(result, date.today())
        if not days:
            raise ValueError("pick the days this order covers")
        for o in self.repo.orders():  # one record per run: a second "placed" replaces it
            if o["run_id"] == rid:
                self.repo.delete_order(int(o["id"]))
        oid = self.repo.record_order(rid, [d.isoformat() for d in days])
        return next(o for o in self.orders_view() if o["id"] == oid)

    def unmark_ordered(self, order_id: int) -> None:
        if not self.repo.delete_order(order_id):
            raise LookupError(f"order {order_id} not found")

    def _source_of(self, rid: int, result: WeekResult, meal: Meal) -> int | None:
        """The run that put ``meal`` into My Week: the applied run when its diff added it, else
        the run an edit was built on, and so on (an edit changes only its own days)."""
        key = (meal.date, meal.recipe_id.key)
        seen: set[int] = set()
        while rid not in seen:
            seen.add(rid)
            if result.plan_diff is None or key in diff_keys(result.plan_diff)[0]:
                return rid
            edit = self.edit_meta(rid)
            if not edit or edit.get("base_run") is None:
                return None
            rid = int(edit["base_run"])
            base = self.repo.get_run(rid)
            if base is None:
                return None
            result = base
        return None

    async def _fresh_dinners(self, week: Week, dates: list[date]) -> dict[date, Meal | None]:
        """Each date's dinner in My Week, read now (the cache is dropped for this)."""
        self._my_week_cache.pop(week.start, None)
        mine = await self.my_week(week)
        return {d: (await self._day_in_my_week(mine, d))[0] for d in dates}

    async def _check_edit_fresh(self, edit: dict[str, Any], week: Week) -> None:
        expect: dict[str, str | None] = edit["expect"]
        now = await self._fresh_dinners(week, [date.fromisoformat(d) for d in expect])
        for d, meal in now.items():
            if (meal.recipe_id.key if meal else None) != expect[d.isoformat()]:
                raise StaleEdit(
                    f"My Week changed on {WEEKDAYS[d.weekday()]} {d.day} since you opened "
                    "this; look again"
                )

    async def _check_proposal_fresh(self, rid: int, result: WeekResult) -> None:
        if result.plan_diff is None:
            return
        self._my_week_cache.pop(result.week.start, None)
        fresh = await self.adapters.sink.diff(result.plan)
        if diff_keys(fresh) != diff_keys(result.plan_diff):
            raise StaleEdit(
                f"My Week changed since run {rid} was planned; plan this week again so "
                "nothing you changed is overwritten"
            )

    async def _week_context(self, week: Week) -> tuple[list[Meal], tuple[Recipe, ...]]:
        """My Week's dinners for ``week`` (the applied plan if it cannot be read) and the
        candidate pool to suggest from: the week's runs first, else the newest run's."""
        applied, awaiting = self._runs_for_week(week)
        try:
            mine = await self.my_week(week)
        except Exception as exc:
            log.warning("could not read My Week for %s: %s", week, exc)
            mine = applied[1].plan if applied else MealPlan(week=week)
        dinners = [dn for d in week.days() if (dn := (await self._day_in_my_week(mine, d))[0])]
        pool: tuple[Recipe, ...] = ()
        for run in (applied, awaiting, self._latest()):
            if run is not None and run[1].candidates:
                pool = run[1].candidates
                break
        return dinners, pool

    def _fits(
        self,
        recipes: tuple[Recipe, ...] | list[Recipe],
        week: Week,
        day: date,
        dinners: list[Meal],
        *,
        strict: bool,
    ) -> list[dict[str, Any]]:
        """``recipes`` that could be the dinner on ``day`` without breaking a hard rule, the
        ones that keep every weekly rule first."""
        household = self.household()
        others = [m for m in dinners if m.date != day]
        current = next((m.recipe_id.key for m in dinners if m.date == day), None)
        known = {k: r for k, r in self._recipes.items()}
        known.update({r.id.key: r for r in recipes})
        # what the week already bends without a dinner on this day is not the suggestion's fault
        before = {
            (v.code, v.message)
            for v in check_plan(MealPlan(week=week, meals=tuple(others)), known, household)
        }
        in_week = {m.recipe_id.key for m in others}
        out: list[dict[str, Any]] = []
        seen_titles: set[str] = set()
        for recipe in recipes:
            # a suggestion must be a dinner, not a side or a basic: enough ingredients
            if recipe.id.key in in_week or recipe.id.key == current:
                continue
            if strict and len(recipe.ingredients) < 4:
                continue
            if recipe.title.lower() in seen_titles:
                continue
            seen_titles.add(recipe.title.lower())
            trial = MealPlan(
                week=week,
                meals=(
                    *others,
                    Meal(
                        date=day,
                        slot=MealSlot.DINNER,
                        recipe_id=recipe.id,
                        servings=household.servings,
                    ),
                ),
            )
            violations = check_plan(trial, known, household)
            if any(v.code in HARD_RULES and v.date in (None, day) for v in violations):
                continue
            mine = [
                v
                for v in violations
                if (v.code, v.message) not in before and v.code not in ("dinner_count", "min_tag")
            ]
            out.append(
                {
                    "recipe_id": recipe.id.key,
                    "title": recipe.title,
                    "minutes": recipe.total_minutes,
                    "tags": sorted(recipe.tags),
                    "spiciness": str(recipe.spiciness),
                    "keeps_rules": not mine,
                    "url": recipe.url,
                }
            )
        out.sort(key=lambda a: (not a["keeps_rules"], a["minutes"] or 999))
        return out

    async def day_alternatives(self, day: date) -> list[dict[str, Any]]:
        """Pre-checked recipes for any day: the pool of the week's runs, checked against what
        My Week holds that week."""
        week = Week.containing(day)
        dinners, pool = await self._week_context(week)
        return self._fits(pool, week, day, dinners, strict=True)[:12]

    async def search_recipes(self, text: str, day: date | None = None) -> list[dict[str, Any]]:
        household = self.household()
        found = await self.adapters.recipes.search(
            RecipeQuery(
                text=text,
                exclude_ingredients=household.rules.banned_ingredients | household.allergies,
                limit=20,
            )
        )
        day = day or date.today()
        week = Week.containing(day)
        dinners, _ = await self._week_context(week)
        return self._fits(list(found), week, day, dinners, strict=False)[:12]

    async def preview_edit(
        self,
        kind: str,
        day: date,
        *,
        recipe_id: str | None = None,
        to: date | None = None,
    ) -> dict[str, Any]:
        """Price one change to My Week and turn it into a run awaiting confirmation. Nothing is
        written to Cookidoo or the store; the returned document is the confirm sheet."""
        if kind not in EDIT_KINDS:
            raise ValueError(f"unknown edit {kind!r}; one of {', '.join(EDIT_KINDS)}")
        today = date.today()
        week = Week.containing(day)
        if day < today or (to is not None and to < today):
            raise ValueError("days in the past cannot be changed")
        if to is not None and to not in week:
            raise ValueError("a dinner moves within its week")
        dates = [day] + ([to] if kind == "move" and to is not None else [])
        self.refuse_if_ordered(dates)
        async with self._lock:
            self._busy = "pricing a change"
            try:
                return await self._preview_edit(kind, day, week, dates, recipe_id, to)
            finally:
                self._busy = None

    async def _preview_edit(
        self,
        kind: str,
        day: date,
        week: Week,
        dates: list[date],
        recipe_id: str | None,
        to: date | None,
    ) -> dict[str, Any]:
        household = self.household()
        try:
            current = await self._fresh_dinners(week, dates)
        except Exception as exc:
            raise StaleEdit(f"My Week cannot be read just now: {exc}") from exc
        new: Meal | None = None
        if recipe_id:
            source, _, external = recipe_id.partition(":")
            new = Meal(
                date=day,
                slot=MealSlot.DINNER,
                recipe_id=RecipeId(source=source, external_id=external),
                servings=household.servings,
            )
        if kind == "swap" and current.get(day) is None:
            kind = "add"
        add, remove = edit_changes(kind, day, current, new=new, to=to)
        plan_diff = PlanDiff(week=week, add=tuple(add), remove=tuple(remove))

        applied, _ = self._runs_for_week(week)
        base = applied[1] if applied else None
        moved_from = {to: day, day: to} if kind == "move" and to is not None else None
        meals = grocery_meals(
            kind, base.plan.meals if base else (), add, dates, moved_from=moved_from
        )
        latest = self._latest()
        known = base.candidates if base else (latest[1].candidates if latest else ())
        result = await run_week(
            household,
            week,
            recipes=self.adapters.recipes,
            store=self.adapters.store,
            sink=self.adapters.sink,
            planner=self.adapters.planner,
            slot=base.shopping.slot if base else None,
            fixed_plan=MealPlan(week=week, meals=meals),
            known_candidates=known,
            channel_overrides=dict(base.channel_overrides) if base else None,
            stop_on_violations=False,
        )
        online_diff = in_store_diff = None
        lines: dict[str, list[dict[str, Any]]] = {"online": [], "in_store": []}
        names = {
            str(c.product.id): c.product.name
            for r in (base, result)
            if r is not None
            for c in (*r.shopping.online, *r.shopping.in_store)
        }
        if household.store_lists is not None:
            for kind_, list_id in (
                ("online", household.store_lists.online),
                ("in_store", household.store_lists.in_store),
            ):
                live = await self.adapters.store.read_list(list_id)
                target = rebase_list(
                    live, _as_list(base, kind_, list_id), _as_list(result, kind_, list_id)
                )
                diff = diff_lists(live, target)
                if kind_ == "online":
                    online_diff = diff
                else:
                    in_store_diff = diff
                before = live.as_dict()
                lines[kind_] = [
                    {
                        "name": names.get(str(c.line.product_id), str(c.line.product_id))
                        if c.line.product_id is not None
                        else c.line.text,
                        "op": c.op,
                        "from": before[c.line.key].quantity if c.line.key in before else 0,
                        "to": 0 if c.op == "remove" else c.line.quantity,
                    }
                    for c in diff.lines
                ]
        result = result.model_copy(
            update={
                "status": PlanStatus.NEEDS_APPROVAL,
                "plan_diff": plan_diff,
                "online_diff": online_diff,
                "in_store_diff": in_store_diff,
                "locked_dates": (),
            }
        )
        rid = self.repo.save_run(result)
        await self._remember_recipes(result)
        for m in add:
            await self._recipe(m.recipe_id)
        cards = {
            "add": [{**(await self._card(m, rid)), "date": m.date.isoformat()} for m in add],
            "remove": [
                {**(await self._card(m, "manual")), "date": m.date.isoformat()} for m in remove
            ],
        }
        title = self._edit_title(kind, day, to, add, remove)
        self.repo.set(
            f"edit.{rid}",
            {
                "kind": kind,
                "day": day.isoformat(),
                "to": to.isoformat() if to else None,
                "base_run": applied[0] if applied else None,
                "title": title,
                "expect": {
                    d.isoformat(): (m.recipe_id.key if m else None) for d, m in current.items()
                },
            },
        )
        # a partial week always misses the count and the minimums; say only what this change bends
        warnings = [
            v.message
            for v in result.violations
            if v.code in (*HARD_RULES, "max_tag", "repeat") and v.date in (None, *dates)
        ]
        return {
            "run_id": rid,
            "kind": kind,
            "title": title,
            "week": week.start.isoformat(),
            "my_week": cards,
            "lists": lines,
            "online_total": str(result.shopping.online_total.amount),
            "online_total_before": str(base.shopping.online_total.amount) if base else None,
            "warnings": warnings,
        }

    def _edit_title(
        self, kind: str, day: date, to: date | None, add: list[Meal], remove: list[Meal]
    ) -> str:
        name = f"{WEEKDAYS[day.weekday()]} {day.day}"
        title = self._title
        if kind == "swap":
            return f"{name}: {title(remove[0].recipe_id.key)} → {title(add[0].recipe_id.key)}"
        if kind == "add":
            return f"{name}: add {title(add[0].recipe_id.key)}"
        if kind == "remove":
            return f"{name}: remove {title(remove[0].recipe_id.key)}"
        assert to is not None
        other = f"{WEEKDAYS[to.weekday()]} {to.day}"
        verb = "swap with" if len(remove) > 1 else "move to"
        return f"{name}: {title(remove[0].recipe_id.key)}, {verb} {other}"

    def discard_edit(self, run_id: int) -> None:
        """Forget a preview that was not confirmed. Nothing was written, so nothing to undo."""
        rid, result = self._run(run_id)
        if self.edit_meta(rid) is None or result.status != PlanStatus.NEEDS_APPROVAL:
            raise ValueError(f"run {rid} is not an open edit")
        self.repo.update_run(rid, result.model_copy(update={"status": PlanStatus.DRAFT}))

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
        # edits are never the proposal awaiting approval (ADR-0014)
        proposals = [r for r in rows if self.edit_meta(int(r["id"])) is None]
        awaiting = (
            proposals[0]
            if proposals
            and proposals[0]["status"] in (PlanStatus.NEEDS_APPROVAL, PlanStatus.NEEDS_INPUT)
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
        orders = self.ordered_dates()
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
                source = (
                    self._source_of(applied[0], applied[1], in_sink)
                    if from_applied and applied
                    else None
                )
                dinner = await self._card(in_sink, source if source is not None else "manual")
                dinner["edited"] = source is not None and self.edit_meta(source) is not None
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
            # the run a proposal's swap and lock act on; dinners in My Week are edited directly
            # (ADR-0014)
            act = awaiting if proposal else None
            groceries = coverage(
                d,
                applied=applied[1] if applied else None,
                from_applied=from_applied,
                proposal=awaiting[1] if awaiting and proposal else None,
                list_members=members,
                today=today,
            )
            order = orders.get(d)
            if order is not None and in_sink is not None:
                groceries = ordered_coverage(groceries)
            records.append(
                {
                    "date": d.isoformat(),
                    "weekday": WEEKDAYS[d.weekday()],
                    "week": w["week"].start.isoformat(),
                    "state": state,
                    "dinner": dinner,
                    "also": [await self._card(m, "manual") for m in rest],
                    "proposal": proposal,
                    "groceries": groceries,
                    "run_id": act[0] if act else None,
                    "locked": bool(act and d in act[1].locked_dates),
                    "my_week_ok": w["ok"],
                    "ordered": order is not None,
                    "order_id": order["id"] if order else None,
                    "lock_reason": lock_reason(order) if order else None,
                    "editable": d >= today and order is None and w["ok"],
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


def _as_list(result: WeekResult | None, kind: str, list_id: str) -> ShoppingList:
    """A run's lines for one of the two store lists, as they were sent."""
    if result is None:
        return ShoppingList(id=list_id)
    s = result.shopping
    if kind == "online":
        return shopping_list_from(list_id, s.online)
    return shopping_list_from(list_id, s.in_store, s.free_text)


def money(value: str) -> Money:
    return Money.chf(value)
