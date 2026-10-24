"""The engine's use cases. One household per engine instance; runs are persisted."""

from __future__ import annotations

import asyncio
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
from znacht_engine.brief import Brief, build_brief, lifetime, price_rows
from znacht_engine.config import EngineSettings
from znacht_engine.repo import Repo
from znacht_engine.wiring import Adapters


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
                locked_meals = tuple(
                    m for m in (base.plan.meals if base else ()) if m.date in locks
                )
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
                            data={"url": self.brief_url(rid), "run_id": str(rid)},
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
        for recipe in result.candidates:
            if recipe.id.key in in_plan:
                continue
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
        if latest is None:
            return {
                "plan_status": "idle",
                "busy": self._busy,
                "run_id": None,
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

    def calendar(self, run_id: int | None = None) -> list[dict[str, Any]]:
        try:
            _, result = self._run(run_id)
        except LookupError:
            return []
        return [
            {
                "date": m.date.isoformat(),
                "slot": str(m.slot),
                "summary": self._recipes[m.recipe_id.key].title
                if m.recipe_id.key in self._recipes
                else m.recipe_id.external_id,
                "recipe_id": m.recipe_id.key,
                "servings": m.servings,
                "url": self._recipes[m.recipe_id.key].url
                if m.recipe_id.key in self._recipes
                else None,
                "note": m.note,
            }
            for m in result.plan.meals
        ]

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
                    data={"url": self.brief_url(run_id), "run_id": str(run_id)},
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
                    data={"url": self.brief_url(run_id), "run_id": str(run_id)},
                )
            )


def money(value: str) -> Money:
    return Money.chf(value)
