"""The engine's use cases. One household per engine instance; runs are persisted."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from znacht.config import load_household
from znacht.domain.household import Household, Pantry, PantryItem
from znacht.domain.money import Money
from znacht.domain.plan import Week
from znacht.domain.quantity import Quantity
from znacht.domain.recipe import Recipe
from znacht.ports.notify import Notifier, PlanEvent
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
    async def plan_week(self, week_start: date | None = None) -> tuple[int, WeekResult]:
        async with self._lock:
            self._busy = "planning"
            try:
                household = self.household()
                week = Week(start=week_start or next_monday())
                result = await run_week(
                    household,
                    week,
                    recipes=self.adapters.recipes,
                    store=self.adapters.store,
                    sink=self.adapters.sink,
                    planner=self.adapters.planner,
                    recent_meals=self.recent_meals(before=week),
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
            return {"plan_status": "idle", "busy": self._busy, "run_id": None}
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
