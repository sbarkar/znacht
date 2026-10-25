"""The engine end to end on the memory adapters: plan, brief, lists, apply, status."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from znacht.domain.plan import Meal, MealSlot
from znacht.domain.recipe import RecipeId
from znacht_engine.app import INGRESS_GATEWAY, create_app
from znacht_engine.config import EngineSettings
from znacht_engine.service import ZnachtService, next_monday
from znacht_memory.fixtures import GOLDEN_WEEK_START


def test_next_monday_is_strictly_in_the_future():
    assert next_monday(date(2026, 10, 26)) == date(2026, 11, 2)  # a Monday rolls to the next one
    assert next_monday(date(2026, 10, 28)) == date(2026, 11, 2)


async def test_requires_the_token(client: httpx.AsyncClient):
    anonymous = httpx.AsyncClient(transport=client._transport, base_url="http://engine.test")
    assert (await anonymous.get("/api/status")).status_code == 401
    assert (await anonymous.get("/healthz")).status_code == 200
    r = await anonymous.get("/brief?token=secret")
    assert r.status_code == 303 and "znacht_token" in r.headers.get("set-cookie", "")


async def test_plan_brief_lists_apply_roundtrip(
    client: httpx.AsyncClient, service: ZnachtService, notifier
):
    assert (await client.get("/api/status")).json()["plan_status"] == "idle"
    run_id, result = await service.plan_week(GOLDEN_WEEK_START)
    assert result.status == "needs_approval"

    status = (await client.get("/api/status")).json()
    assert status["run_id"] == run_id and status["plan_status"] == "needs_approval"
    assert status["meets_minimum"] is True
    assert status["brief_url"] == f"http://engine.test/brief/{run_id}?token=secret"

    page = await client.get(f"/brief/{run_id}")
    assert page.status_code == 200
    html = page.text
    assert "Store run, in walking order" in html and "Approve: send plan and lists" in html
    assert "Yogurt natural" in html and "per person" in html

    lists = (await client.get("/api/lists")).json()
    assert lists["online"] and lists["in_store"]
    assert any(i["summary"] == "dishwasher tabs" for i in lists["in_store"])
    uid = lists["online"][0]["uid"]
    await client.post("/api/lists/online/done", json={"uid": uid, "done": True})
    await client.post("/api/lists/in_store/items", json={"summary": "birthday candles"})
    lists = (await client.get("/api/lists")).json()
    assert next(i for i in lists["online"] if i["uid"] == uid)["done"] is True
    assert any(i["summary"] == "birthday candles" for i in lists["in_store"])

    calendar = (await client.get("/api/calendar")).json()
    assert len(calendar) == 7 and calendar[0]["date"] == GOLDEN_WEEK_START.isoformat()

    assert [e.kind for e in notifier.events] == ["plan_ready"]
    assert "approve" in notifier.events[0].actions

    applied = await client.post(f"/api/apply?run_id={run_id}")
    assert applied.status_code == 200 and applied.json()["status"] == "applied"
    assert (await client.get("/api/status")).json()["plan_status"] == "applied"
    assert notifier.events[-1].kind == "applied"
    assert service.repo.ledger()[0]["week"] == GOLDEN_WEEK_START.isoformat()
    assert service.repo.get("preferred.overlay") == {"yogurt": "p-yog-natural"}
    # applying twice is refused
    assert (await client.post(f"/api/apply?run_id={run_id}")).status_code == 409


async def test_pantry_overlay_changes_the_next_plan(
    client: httpx.AsyncClient, service: ZnachtService
):
    r = await client.post("/api/pantry", json={"items": {"tahini": "250 g"}})
    assert r.status_code == 200
    assert service.household().pantry.get("tahini") is not None
    _, result = await service.plan_week(GOLDEN_WEEK_START)
    assert all(c.need_name != "tahini" for c in result.shopping.online)


async def test_plan_week_endpoint_runs_in_background(
    client: httpx.AsyncClient, service: ZnachtService
):
    r = await client.post("/api/plan_week", json={"week": GOLDEN_WEEK_START.isoformat()})
    assert r.status_code == 200 and r.json()["accepted"]
    for _ in range(50):
        await asyncio.sleep(0.05)
        if service.repo.latest_run("example"):
            break
    assert service.repo.latest_run("example") is not None


async def test_revert_restores_my_week_and_lists(client: httpx.AsyncClient, service: ZnachtService):
    from datetime import date as _date

    from znacht.domain.plan import Meal, MealPlan, MealSlot, Week
    from znacht.domain.recipe import RecipeId

    # the household already had a plan in the sink before Znacht ran
    week = Week(start=GOLDEN_WEEK_START)
    existing = Meal(
        date=_date(2026, 10, 27),
        slot=MealSlot.DINNER,
        recipe_id=RecipeId(source="memory", external_id="omelette"),
        servings=2,
    )
    await service.adapters.sink.apply(
        await service.adapters.sink.diff(MealPlan(week=week, meals=(existing,)))
    )
    online_before = await service.adapters.store.read_list("list-online")

    run_id, _ = await service.plan_week(GOLDEN_WEEK_START)
    applied = await client.post(f"/api/apply?run_id={run_id}")
    assert applied.json()["status"] == "applied"
    assert existing not in (await service.adapters.sink.read_week(week)).meals

    reverted = await client.post(f"/api/runs/{run_id}/revert")
    assert reverted.status_code == 200 and reverted.json()["status"] == "reverted"
    assert set((await service.adapters.sink.read_week(week)).meals) == {existing}
    assert (
        await service.adapters.store.read_list("list-online")
    ).as_dict().keys() == online_before.as_dict().keys()
    assert (await client.post(f"/api/runs/{run_id}/revert")).status_code == 409


async def test_app_verbs_view_alternatives_swap_lock_move(
    client: httpx.AsyncClient, service: ZnachtService
):
    run_id, _ = await service.plan_week(GOLDEN_WEEK_START)
    view = (await client.get(f"/api/runs/{run_id}/view")).json()
    assert (
        view["run_id"] == run_id
        and len(view["dinners"]) == 7
        and view["money"]["meets_minimum"] is True
    )
    assert (await client.get("/api/view")).json()["run_id"] == run_id
    assert (await client.get("/api/household")).json()["members"][0]["name"]

    day = view["dinners"][3]["date"]
    alts = (await client.get(f"/api/runs/{run_id}/alternatives?day={day}")).json()
    assert alts, "the pool has alternatives for a midweek dinner"
    assert all(a["recipe_id"] != view["dinners"][3]["recipe_id"] for a in alts)
    assert all("dill" not in a["title"].lower() for a in alts)

    swapped = (
        await client.post(
            f"/api/runs/{run_id}/swap", json={"date": day, "recipe_id": alts[0]["recipe_id"]}
        )
    ).json()
    assert swapped["run_id"] == run_id + 1
    assert (
        next(d for d in swapped["dinners"] if d["date"] == day)["recipe_id"] == alts[0]["recipe_id"]
    )
    assert swapped["status"] in ("needs_approval", "needs_input")

    locked = (
        await client.post(f"/api/runs/{swapped['run_id']}/lock", json={"date": day, "locked": True})
    ).json()
    assert next(d for d in locked["dinners"] if d["date"] == day)["locked"] is True

    online_need = swapped["online"][0]["need"]
    moved = (
        await client.post(
            f"/api/runs/{swapped['run_id']}/move", json={"need": online_need, "to": "store"}
        )
    ).json()
    assert all(line["need"] != online_need for line in moved["online"])
    assert any(line["need"] == online_need for line in moved["in_store"])

    page = await client.get("/app")
    assert page.status_code == 200 and "app.js" in page.text
    assert (await client.get("/app/static/app.css")).status_code == 200


async def test_household_patch_keeps_yaml_comments(client: httpx.AsyncClient, settings, tmp_path):
    import shutil

    target = tmp_path / "household.yaml"
    shutil.copy(settings.household_path, target)
    object.__setattr__(settings, "household_path", target)
    before = target.read_text()
    assert "# One household per file" in before
    r = await client.patch(
        "/api/household",
        json={
            "rules": {"min_per_week": {"fish": 3}},
            "pantry": {"tahini": "250 g", "salt": "0"},
            "members": [
                {"name": "Sergej", "age_group": "adult", "dislikes": ["dill", "olives"]},
                {"name": "Partner", "age_group": "adult"},
                {"name": "Toddler", "age_group": "toddler"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    after = target.read_text()
    assert "# One household per file" in after  # comments survive
    assert "fish: 3" in after and "tahini: 250 g" in after and "salt:" not in after
    h = r.json()
    assert h["rules"]["min_tags"]["fish"] == 3 and "olives" in h["members"][0]["dislikes"]
    bad = await client.patch("/api/household", json={"rules": {"dinners_per_week": "seven"}})
    assert bad.status_code == 422


# -- the timeline: My Week is the truth, runs are proposals (ADR-0011) ----------------------


def _meal(day: date, recipe: str, servings: int = 3):
    return Meal(
        date=day,
        slot=MealSlot.DINNER,
        recipe_id=RecipeId(source="memory", external_id=recipe),
        servings=servings,
    )


async def _put_in_my_week(service: ZnachtService, *meals):
    from znacht.domain.plan import MealPlan, Week

    by_week: dict[date, list] = {}
    for m in meals:
        by_week.setdefault(Week.containing(m.date).start, []).append(m)
    for start, ms in by_week.items():
        week = Week(start=start)
        current = await service.adapters.sink.read_week(week)
        plan = MealPlan(week=week, meals=(*current.meals, *ms))
        await service.adapters.sink.apply(await service.adapters.sink.diff(plan))
    service.forget_live_reads()


def test_timeline_helpers_span_and_summary():
    from znacht_engine.timeline import span, summary

    mon = date(2026, 10, 26)
    assert span([mon, mon + timedelta(1), mon + timedelta(2), mon + timedelta(5)]) == "Mon–Wed, Sat"
    assert span([]) == ""
    days = [
        {
            "date": "2026-10-26",
            "state": "planned",
            "dinner": {},
            "groceries": {"coverage": "store_run", "label": "store run"},
        },
        {
            "date": "2026-10-27",
            "state": "planned",
            "dinner": {},
            "groceries": {"coverage": "arriving", "label": "arriving Mon 19:00"},
        },
        {
            "date": "2026-10-28",
            "state": "planned",
            "dinner": {},
            "groceries": {"coverage": "arriving", "label": "arriving Mon 19:00"},
        },
        {
            "date": "2026-10-29",
            "state": "proposed",
            "dinner": None,
            "groceries": {"coverage": "none", "label": "none"},
        },
        {
            "date": "2026-10-30",
            "state": "planned",
            "dinner": {},
            "groceries": {"coverage": "none", "label": "none"},
        },
        {
            "date": "2026-10-31",
            "state": "empty",
            "dinner": None,
            "groceries": {"coverage": "none", "label": "none"},
        },
        {
            "date": "2026-11-01",
            "state": "empty",
            "dinner": None,
            "groceries": {"coverage": "none", "label": "none"},
        },
    ]
    assert summary(days, awaiting_run_id=13) == (
        "4 of 7 planned · 1 proposed (run 13 awaits approval) · online order Mon 19:00 covers "
        "Tue–Wed · store run Mon · Fri no groceries · Sat–Sun nothing yet"
    )


async def test_timeline_states_sources_and_coverage(
    client: httpx.AsyncClient, service: ZnachtService
):
    mon = GOLDEN_WEEK_START
    # a dinner the household put into My Week by hand, before Znacht ran
    await _put_in_my_week(service, _meal(mon + timedelta(days=2), "omelette"))

    # nothing planned by Znacht yet: one manual day, the rest empty, past days collapsed
    r = await client.get(f"/api/timeline?from={mon - timedelta(days=2)}&days=9")
    assert r.status_code == 200
    tl = r.json()
    assert tl["from"] == (mon - timedelta(days=2)).isoformat() and tl["horizon"] == 9
    by_date = {d["date"]: d for d in tl["days"]}
    assert len(by_date) == 9 and len(tl["weeks"]) == 2
    wed = by_date[(mon + timedelta(days=2)).isoformat()]
    assert wed["state"] == "planned" and wed["dinner"]["source"] == "manual"
    assert wed["dinner"]["title"].startswith("Omelette")
    assert wed["groceries"]["coverage"] == "none"
    assert wed["run_id"] is None  # nothing to swap within: it is yours
    assert by_date[mon.isoformat()]["state"] == "empty"
    this_week = next(w for w in tl["weeks"] if w["week"] == mon.isoformat())
    assert this_week["locked_dates"] == [(mon + timedelta(days=2)).isoformat()]
    assert this_week["awaiting_run_id"] is None and this_week["applied_run_id"] is None
    assert this_week["summary"].startswith("1 of 7 planned")
    assert "Thu–Sun nothing yet" in this_week["summary"]

    # a proposal: run awaits approval, My Week untouched
    run_id, result = await service.plan_week(mon)
    assert result.status == "needs_approval"
    tl = (await client.get(f"/api/timeline?from={mon}&days=7")).json()
    by_date = {d["date"]: d for d in tl["days"]}
    assert by_date[mon.isoformat()]["state"] == "proposed"
    assert by_date[mon.isoformat()]["proposal"]["source"] == run_id
    assert by_date[mon.isoformat()]["run_id"] == run_id  # the swap sheet acts on the proposal
    wed = by_date[(mon + timedelta(days=2)).isoformat()]
    assert wed["state"] == "planned" and wed["dinner"]["source"] == "manual"
    assert wed["proposal"] is not None and wed["proposal"]["source"] == run_id
    week = tl["weeks"][0]
    assert week["awaiting_run_id"] == run_id and week["awaiting_status"] == "needs_approval"
    assert f"6 proposed (run {run_id} awaits approval)" in week["summary"]
    assert set(tl["proposed_dates"]) == {d for d in by_date if d != wed["date"]}
    assert tl["unplanned_dates"] == tl["proposed_dates"] and tl["empty_dates"] == []
    # proposed dinners are not covered: nothing is on the store's lists yet
    assert all(by_date[d]["groceries"]["coverage"] == "none" for d in by_date)

    # approved: My Week now carries the run's dinners, groceries are covered by its lists
    assert (await client.post(f"/api/apply?run_id={run_id}")).json()["status"] == "applied"
    tl = (await client.get(f"/api/timeline?from={mon}&days=7")).json()
    by_date = {d["date"]: d for d in tl["days"]}
    assert all(d["state"] == "planned" for d in by_date.values())
    assert all(d["dinner"]["source"] == run_id for d in by_date.values())
    # a dinner in My Week is edited directly (ADR-0014): no run to swap on, and editable
    assert all(d["run_id"] is None and d["proposal"] is None for d in by_date.values())
    assert all(d["editable"] == (d["date"] >= tl["today"]) for d in by_date.values())
    assert not any(d["ordered"] for d in by_date.values())
    # the golden week delivers Monday 19:00–21:00: Monday is a store run, Tue–Sun arrive
    assert by_date[mon.isoformat()]["groceries"]["coverage"] == "store_run"
    tue = by_date[(mon + timedelta(days=1)).isoformat()]["groceries"]
    # "arriving" until the slot has passed, "delivered" after (the label follows the real date)
    assert tue["coverage"] == "arriving" and tue["label"].endswith(" Mon 19:00")
    assert tue["slot"].startswith(mon.isoformat())
    week = tl["weeks"][0]
    assert week["applied_run_id"] == run_id and week["awaiting_run_id"] is None
    assert week["summary"] == (
        "7 of 7 planned · online order Mon 19:00 covers Tue–Sun · store run Mon"
    )
    assert tl["unplanned_dates"] == []

    # the household changes Wednesday by hand in My Week: it becomes theirs, groceries unknown
    from znacht.domain.plan import MealPlan, Week

    wk = Week(start=mon)
    current = await service.adapters.sink.read_week(wk)
    changed = MealPlan(
        week=wk,
        meals=(
            *(m for m in current.meals if m.date != mon + timedelta(days=2)),
            _meal(mon + timedelta(days=2), "veg-pasta"),
        ),
    )
    await service.adapters.sink.apply(await service.adapters.sink.diff(changed))
    service.forget_live_reads()
    tl = (await client.get(f"/api/timeline?from={mon}&days=7")).json()
    wed = next(d for d in tl["days"] if d["date"] == (mon + timedelta(days=2)).isoformat())
    assert wed["dinner"]["source"] == "manual" and wed["dinner"]["title"].startswith("Pasta")
    assert wed["groceries"]["coverage"] == "none"
    assert "Wed no groceries" in tl["weeks"][0]["summary"]

    # the calendar carries the manual dinner too, with its source
    cal = (await client.get("/api/calendar")).json()
    by_cal = {c["date"]: c for c in cal}
    assert by_cal[wed["date"]]["source"] == "manual" and by_cal[wed["date"]]["proposed"] is False
    assert by_cal[mon.isoformat()]["source"] == run_id


def test_breakfasts_are_told_apart_by_tag_or_title():
    from znacht.domain.plan import MealSlot
    from znacht.domain.recipe import Recipe, Tag
    from znacht_engine.timeline import is_breakfast, pick_dinner

    def recipe(key: str, title: str, tags: frozenset[str] = frozenset()) -> Recipe:
        return Recipe(
            id=RecipeId(source="cookidoo", external_id=key),
            title=title,
            servings=4,
            ingredients=(),
            tags=frozenset(tags),
        )

    muesli = recipe("r1", "Bircher Müsli")
    eggs = recipe("r2", "Eggs royale", frozenset({Tag.BREAKFAST}))
    curry = recipe("r3", "Creamy coconut chicken curry (TM6)")
    by_key = {r.id.key: r for r in (muesli, eggs, curry)}
    day = date(2026, 10, 27)
    meals = [
        Meal(date=day, slot=MealSlot.DINNER, recipe_id=r.id, servings=3)
        for r in (muesli, eggs, curry)
    ]
    assert is_breakfast(meals[0], muesli) and is_breakfast(meals[1], eggs)
    assert not is_breakfast(meals[2], curry)
    assert is_breakfast(meals[2], None) is False  # unknown recipe, non-breakfast id
    dinner, rest = pick_dinner(meals, lambda m: by_key[m.recipe_id.key])
    assert dinner is meals[2] and rest == meals[:2]
    dinner, rest = pick_dinner(meals[:2], lambda m: by_key[m.recipe_id.key])
    assert dinner is None and rest == meals[:2]


async def test_timeline_skips_breakfasts_and_lists_the_rest_of_the_day(
    client: httpx.AsyncClient, service: ZnachtService
):
    from znacht.domain.recipe import Recipe, Tag

    mon = GOLDEN_WEEK_START
    muesli = Recipe(
        id=RecipeId(source="memory", external_id="bircher"),
        title="Bircher Müsli",
        servings=4,
        ingredients=(),
        tags=frozenset({Tag.BREAKFAST}),
    )
    service._recipes[muesli.id.key] = muesli  # not in the fixture source: comes from the cache
    tue, wed = mon + timedelta(days=1), mon + timedelta(days=2)
    # Tuesday: breakfast first, then the dinner; Wednesday: a breakfast only
    await _put_in_my_week(
        service, _meal(tue, "bircher"), _meal(tue, "omelette"), _meal(wed, "bircher")
    )
    tl = (await client.get(f"/api/timeline?from={mon}&days=7")).json()
    by_date = {d["date"]: d for d in tl["days"]}
    t, w = by_date[tue.isoformat()], by_date[wed.isoformat()]
    assert t["state"] == "planned" and t["dinner"]["title"].startswith("Omelette")
    assert [a["title"] for a in t["also"]] == ["Bircher Müsli"] and t["also"][0]["breakfast"]
    assert w["state"] == "empty" and w["dinner"] is None
    assert [a["title"] for a in w["also"]] == ["Bircher Müsli"]
    assert tl["weeks"][0]["locked_dates"] == [tue.isoformat()]  # Wednesday is still a gap
    assert tl["empty_dates"] == [d for d in by_date if d != tue.isoformat()]

    cal = (await client.get("/api/calendar")).json()
    on_tue = sorted((c["slot"], c["summary"]) for c in cal if c["date"] == tue.isoformat())
    assert on_tue[0] == ("breakfast", "Bircher Müsli") and on_tue[1][0] == "dinner"
    assert any(c["date"] == wed.isoformat() and c["slot"] == "breakfast" for c in cal)

    # Plan the gaps locks Tuesday's dinner, not its breakfast
    r = await client.post(
        "/api/plan_week", json={"week": mon.isoformat(), "locked_dates": [tue.isoformat()]}
    )
    assert r.status_code == 200
    for _ in range(100):
        await asyncio.sleep(0.05)
        if service.repo.latest_run("example"):
            break
    _, result = service.repo.latest_run("example")
    locked = [m for m in result.plan.meals if m.date == tue]
    assert [m.recipe_id.external_id for m in locked] == ["omelette"]


async def test_timeline_my_week_cache_and_bounds(client: httpx.AsyncClient, service: ZnachtService):
    calls = 0
    real = service.adapters.sink.read_week

    async def counting(week):
        nonlocal calls
        calls += 1
        return await real(week)

    service.adapters.sink.read_week = counting  # type: ignore[method-assign]
    await client.get(f"/api/timeline?from={GOLDEN_WEEK_START}&days=14")
    await client.get(f"/api/timeline?from={GOLDEN_WEEK_START}&days=14")
    assert calls == 2  # two ISO weeks, read once each; the second call is served from cache
    assert (await client.get("/api/timeline?days=0")).status_code == 422
    assert (await client.get("/api/timeline?days=99")).status_code == 422
    assert (await client.get("/api/timeline?from=not-a-date")).status_code == 422
    default = (await client.get("/api/timeline")).json()
    assert default["horizon"] == 14 and default["from"] == default["today"]


async def test_plan_the_gaps_locks_my_week_dinners(
    client: httpx.AsyncClient, service: ZnachtService
):
    mon = GOLDEN_WEEK_START
    mine = (_meal(mon + timedelta(days=1), "omelette"), _meal(mon + timedelta(days=4), "veg-pasta"))
    await _put_in_my_week(service, *mine)
    tl = (await client.get(f"/api/timeline?from={mon}&days=7")).json()
    locked = tl["weeks"][0]["locked_dates"]
    assert locked == [m.date.isoformat() for m in mine]

    # what the app's "Plan the gaps" button sends
    r = await client.post("/api/plan_week", json={"week": mon.isoformat(), "locked_dates": locked})
    assert r.status_code == 200 and r.json()["accepted"]
    for _ in range(100):
        await asyncio.sleep(0.05)
        if service.repo.latest_run("example"):
            break
    _, result = service.repo.latest_run("example")
    assert [d.isoformat() for d in result.locked_dates] == locked
    assert len(result.plan.meals) == 7
    for m in mine:
        assert m in result.plan.meals  # kept, servings and all
    # approving would add the gaps only: nothing of yours is removed from My Week
    assert result.plan_diff is not None and result.plan_diff.remove == ()
    assert {m.date for m in result.plan_diff.add} == {
        mon + timedelta(days=i) for i in (0, 2, 3, 5, 6)
    }
    tl = (await client.get(f"/api/timeline?from={mon}&days=7")).json()
    by_date = {d["date"]: d for d in tl["days"]}
    assert by_date[mine[0].date.isoformat()]["state"] == "planned"
    assert by_date[mine[0].date.isoformat()]["proposal"] is None
    assert by_date[mon.isoformat()]["state"] == "proposed"
    assert tl["weeks"][0]["summary"].startswith("2 of 7 planned · 5 proposed")

    # approved: the kept dinners stay yours but the run's lists cover them too
    run_id = service.repo.latest_run("example")[0]
    assert (await client.post(f"/api/apply?run_id={run_id}")).json()["status"] == "applied"
    tl = (await client.get(f"/api/timeline?from={mon}&days=7")).json()
    by_date = {d["date"]: d for d in tl["days"]}
    tue, fri = by_date[mine[0].date.isoformat()], by_date[mine[1].date.isoformat()]
    assert tue["dinner"]["source"] == "manual" and fri["dinner"]["source"] == "manual"
    assert tue["groceries"]["coverage"] == "arriving" and fri["groceries"]["coverage"] == "arriving"
    assert by_date[mon.isoformat()]["dinner"]["source"] == run_id
    assert tue["run_id"] is None and tue["editable"]  # edited directly (ADR-0014)


async def test_shopping_run_is_the_applied_week_not_the_newest_proposal(
    client: httpx.AsyncClient, service: ZnachtService
):
    """Planning next week must not take away the list the household is shopping with."""
    this, _ = await service.plan_week(GOLDEN_WEEK_START)
    assert service.shopping_run_id(today=GOLDEN_WEEK_START) == this  # nothing applied: latest
    await service.apply(this)
    nxt, _ = await service.plan_week(GOLDEN_WEEK_START + timedelta(days=7))
    assert service.shopping_run_id(today=GOLDEN_WEEK_START) == this
    # a week later the applied week is behind us and the newest run is what's left
    assert service.shopping_run_id(today=GOLDEN_WEEK_START + timedelta(days=7)) == nxt
    assert "shopping_run_id" in (await client.get("/api/status")).json()


async def test_ticks_and_free_text_follow_the_run_on_screen(
    client: httpx.AsyncClient, service: ZnachtService
):
    first, result = await service.plan_week(GOLDEN_WEEK_START)
    await service.plan_week(GOLDEN_WEEK_START + timedelta(days=7))  # now the latest run
    uid = f"online:{result.shopping.online[0].product.id}"
    r = await client.post(f"/api/lists/online/done?run_id={first}", json={"uid": uid, "done": True})
    assert r.status_code == 200
    r = await client.post(
        f"/api/lists/in_store/items?run_id={first}", json={"summary": " cat food "}
    )
    assert r.status_code == 200
    todo = (await client.get(f"/api/runs/{first}/view")).json()["todo"]
    assert any(i["uid"] == uid and i["done"] for i in todo["online"])
    assert any(i["uid"] == "text:cat food" for i in todo["in_store"])
    assert (
        await client.post("/api/lists/in_store/items", json={"summary": "  "})
    ).status_code == 422
    missing = await client.post(
        "/api/lists/online/done?run_id=999", json={"uid": uid, "done": True}
    )
    assert missing.status_code == 404

    # a move derives a new run; the shopping state comes along
    need = result.shopping.online[0].need_name
    moved = (
        await client.post(f"/api/runs/{first}/move", json={"need": need, "to": "store"})
    ).json()
    todo = moved["todo"]
    assert any(i["uid"] == "text:cat food" for i in todo["in_store"])


async def test_store_lines_carry_their_aisle_and_failures_surface(
    client: httpx.AsyncClient, service: ZnachtService
):
    run_id, _ = await service.plan_week(GOLDEN_WEEK_START)
    view = (await client.get(f"/api/runs/{run_id}/view")).json()
    assert view["in_store"] and all(line["aisle"] for line in view["in_store"])
    service.repo.set("last_error", "Cookidoo said no")
    assert (await client.get("/api/status")).json()["last_error"] == "Cookidoo said no"
    await service.plan_week(GOLDEN_WEEK_START)
    assert (await client.get("/api/status")).json()["last_error"] is None


async def test_a_later_week_does_not_take_this_weeks_delivery_slot(service: ZnachtService):
    """The fake store lists one slot, on the golden Monday; a plan for the week after must not
    have its groceries delivered a week early."""
    _, now = await service.plan_week(GOLDEN_WEEK_START)
    assert now.shopping.slot is not None
    later = GOLDEN_WEEK_START + timedelta(days=7)
    _, result = await service.plan_week(later)
    slot = result.shopping.slot
    assert slot is None or slot.delivery_day >= later - timedelta(days=3)


async def test_plan_week_takes_any_day_of_the_week(
    client: httpx.AsyncClient, service: ZnachtService
):
    wednesday = GOLDEN_WEEK_START + timedelta(days=2)
    r = await client.post("/api/plan_week", json={"week": wednesday.isoformat()})
    assert r.status_code == 200
    for _ in range(100):
        await asyncio.sleep(0.02)
        if not service.busy and service.repo.latest_run(service.household().id):
            break
    _, result = service.repo.latest_run(service.household().id) or (None, None)
    assert result is not None and result.week.start == GOLDEN_WEEK_START
    assert service.repo.get("last_error") is None


async def test_app_edits_keep_spice_settings_and_remove_overlaid_pantry_items(
    client: httpx.AsyncClient, settings, tmp_path
):
    """The app sends members back as it got them; a written mild_food must survive that, and
    removing a pantry chip must remove it even when Home Assistant put it there."""
    import shutil

    target = tmp_path / "household.yaml"
    shutil.copy(settings.household_path, target)
    object.__setattr__(settings, "household_path", target)
    members = (await client.get("/api/household")).json()["members"]
    members[0]["mild_food"] = True
    r = await client.patch("/api/household", json={"members": members})
    members = r.json()["members"]
    assert members[0]["mild_food"] is True
    members[1]["dislikes"] = ["capers"]  # an unrelated edit, round-tripping the list
    r = await client.patch("/api/household", json={"members": members})
    assert r.json()["members"][0]["mild_food"] is True

    await client.post("/api/pantry", json={"items": {"tahini": "250 g"}})
    names = [p["name"] for p in (await client.get("/api/household")).json()["pantry"]]
    assert "tahini" in names
    r = await client.patch("/api/household", json={"pantry": {"tahini": "0"}})
    assert "tahini" not in [p["name"] for p in r.json()["pantry"]]


async def test_a_delivery_in_the_past_reads_delivered(service: ZnachtService):
    from znacht_engine.timeline import coverage

    _, result = await service.plan_week(GOLDEN_WEEK_START)
    wed = GOLDEN_WEEK_START + timedelta(days=2)
    kw = {"applied": result, "from_applied": True, "proposal": None, "list_members": {}}
    assert coverage(wed, today=GOLDEN_WEEK_START, **kw)["label"] == "arriving Mon 19:00"
    late = coverage(wed, today=wed, **kw)
    assert late["coverage"] == "arriving" and late["label"] == "delivered Mon 19:00"


INGRESS = "/api/hassio_ingress/abc_DEF-123"


def _client_from(app, peer: str, **headers: str) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(peer, 40000))
    return httpx.AsyncClient(transport=transport, base_url="http://engine.test", headers=headers)


async def test_ingress_gateway_is_trusted_and_urls_carry_its_path(settings, service):
    app = create_app(replace(settings, ingress=True), service)
    async with (
        app.router.lifespan_context(app),
        _client_from(app, INGRESS_GATEWAY, **{"X-Ingress-Path": INGRESS}) as c,
    ):
        assert (await c.get("/api/status")).status_code == 200  # no token: HA checked the user
        root = await c.get("/")
        assert root.status_code == 302 and root.headers["location"] == f"{INGRESS}/app"
        page = (await c.get("/app")).text
        assert f'data-base="{INGRESS}"' in page and f'src="{INGRESS}/app/static/app.js' in page
        run_id, _ = await service.plan_week(GOLDEN_WEEK_START)
        assert f'action="{INGRESS}/brief/{run_id}/apply' in (await c.get(f"/brief/{run_id}")).text
        r = await c.get(f"/brief/{run_id}?token=x")
        assert r.headers["location"] == f"{INGRESS}/brief/{run_id}"


async def test_ingress_trust_needs_the_flag_the_gateway_and_a_sane_path(settings, service):
    ingress_app = create_app(replace(settings, ingress=True), service)
    plain_app = create_app(settings, service)
    async with ingress_app.router.lifespan_context(ingress_app):
        # another peer still needs the token, and its X-Ingress-Path is ignored
        async with _client_from(ingress_app, "172.30.33.7", **{"X-Ingress-Path": INGRESS}) as c:
            assert (await c.get("/api/status")).status_code == 401
            assert 'data-base=""' in (await c.get("/app")).text
        # a malformed path from the gateway is not echoed into the page
        async with _client_from(ingress_app, INGRESS_GATEWAY, **{"X-Ingress-Path": '/x"><b>'}) as c:
            assert 'data-base=""' in (await c.get("/app")).text
    # without ZNACHT_INGRESS the gateway address means nothing
    async with (
        plain_app.router.lifespan_context(plain_app),
        _client_from(plain_app, INGRESS_GATEWAY) as c,
    ):
        assert (await c.get("/api/status")).status_code == 401


async def test_notifications_open_the_configured_link(settings, notifier, service):
    service.settings = replace(settings, notify_link="/abc123_znacht")
    await service.plan_week(GOLDEN_WEEK_START)
    assert notifier.events[-1].data["url"] == "/abc123_znacht"
    assert service.status()["brief_url"].startswith(
        "http://engine.test/brief/"
    )  # the app still links the Brief


# -- first setup in the app, connections (ADR-0013) -----------------------------------------

WIZARD = {
    "name": "The Müllers",
    "members": [
        {"name": "Anna", "age_group": "adult", "dislikes": ["dill"]},
        {"name": " ", "age_group": "adult"},  # an empty row is dropped
        {"name": "Leo", "age_group": "toddler"},
    ],
    "rules": {
        "dinners_per_week": 5,
        "max_total_minutes_weekday": 45,
        "min_per_week": {"fish": 1, "legumes": 0},
        "max_per_week": {"red_meat": 1},
    },
    "delivery": {"postcode": "8004", "weekday": 0, "start": "18:00", "end": "20:00"},
    "store_lists": {"online": "list-online", "in_store": "list-store"},
}


def _fresh_service(settings, service, tmp_path):
    household = tmp_path / "household.yaml"
    household.write_text(Path(settings.household_path).read_text(encoding="utf-8"))
    object.__setattr__(settings, "household_path", household)  # like the tests above
    assert service.settings is settings
    return household


async def test_the_wizard_replaces_the_example_and_keeps_it(client, settings, service, tmp_path):
    household = _fresh_service(settings, service, tmp_path)
    assert (await client.get("/api/setup")).json()["needed"] is True
    view = (await client.post("/api/setup", json=WIZARD)).json()
    assert view["id"] == "the-müllers" and view["name"] == "The Müllers"
    assert [m["name"] for m in view["members"]] == ["Anna", "Leo"]
    assert view["needs_mild_food"] is True  # the toddler
    assert view["rules"]["min_tags"] == {"fish": 1} and view["rules"]["max_tags"] == {"red_meat": 1}
    assert view["delivery"]["slots"] == [
        {"id": "mon-18-20", "weekday": 0, "start": "18:00", "end": "20:00"}
    ]
    assert view["store_lists"] == {"online": "list-online", "in_store": "list-store"}
    assert '"18:00"' in household.read_text()  # quoted: YAML 1.1 reads 18:00 as 1080
    assert (tmp_path / "household.example.yaml").read_text().startswith("# One household")
    assert (await client.get("/api/setup")).json()["needed"] is False
    _, result = await service.plan_week(GOLDEN_WEEK_START)
    assert result.status == "needs_approval"


async def test_a_zero_maximum_from_the_wizard_means_never(client, settings, service, tmp_path):
    _fresh_service(settings, service, tmp_path)
    rules = {**WIZARD["rules"], "max_per_week": {"red_meat": 0}}
    view = (await client.post("/api/setup", json={**WIZARD, "rules": rules})).json()
    assert view["rules"]["max_tags"] == {"red_meat": 0}


async def test_a_wizard_mistake_keeps_the_old_file(client, settings, service, tmp_path):
    household = _fresh_service(settings, service, tmp_path)
    before = household.read_text()
    r = await client.post("/api/setup", json={**WIZARD, "delivery": {"postcode": ""}})
    assert r.status_code == 422 and "postcode" in r.json()["detail"]
    r = await client.post("/api/setup", json={**WIZARD, "members": [{"name": ""}]})
    assert r.status_code == 422
    assert household.read_text() == before and not (tmp_path / "household.example.yaml").exists()


async def test_household_edits_the_delivery_slot(client, settings, service, tmp_path):
    household = _fresh_service(settings, service, tmp_path)
    await client.post("/api/setup", json=WIZARD)
    slot = {"id": "wed-17-19", "weekday": 2, "start": "17:00", "end": "19:00"}
    r = await client.patch(
        "/api/household",
        json={"delivery": {"preferred_slot_id": slot["id"], "slot_templates": [slot]}},
    )
    assert r.status_code == 200 and r.json()["delivery"]["slots"] == [slot]
    assert r.json()["delivery"]["postcode"] == "8004"  # the rest of delivery stays
    assert '"17:00"' in household.read_text()


async def test_store_lists_and_connections(client):
    lists = (await client.get("/api/store/lists")).json()
    assert {"id": "list-online", "name": "Online basket"} in lists
    checks = (await client.get("/api/connections")).json()
    assert all(c["ok"] for c in checks.values())


async def test_a_failed_login_does_not_stop_the_engine(monkeypatch, tmp_path):
    import znacht_cookidoo
    from znacht_engine.repo import Repo
    from znacht_engine.wiring import Unavailable, build_adapters

    class Refusing:
        def __init__(self, settings):
            pass

        async def __aenter__(self):
            raise PermissionError("401 wrong password")

        async def __aexit__(self, *exc):
            return None

    monkeypatch.setattr(znacht_cookidoo, "CookidooSession", Refusing)
    monkeypatch.setenv("ZNACHT_COOKIDOO_EMAIL", "a@b.ch")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = EngineSettings(
        household_path=tmp_path / "h.yaml",
        data_dir=tmp_path,
        recipe_source="cookidoo",
        sink="cookidoo",
        planner="anthropic",
    )
    adapters = await build_adapters(s, Repo(tmp_path / "x.sqlite"))
    assert isinstance(adapters.recipes, Unavailable) and isinstance(adapters.sink, Unavailable)
    assert "wrong password" in adapters.problems["cookidoo"]
    assert adapters.problems["anthropic"] == "Claude needs an API key"
    with pytest.raises(RuntimeError, match="wrong password"):
        await adapters.recipes.search(None)
    await adapters.close()
