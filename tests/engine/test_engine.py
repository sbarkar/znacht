"""The engine end to end on the memory adapters: plan, brief, lists, apply, status."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import httpx

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
    from znacht.domain.plan import Meal, MealSlot
    from znacht.domain.recipe import RecipeId

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
        "Tue–Wed · store run Mon · Thu–Fri no groceries · Sat–Sun nothing yet"
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
    assert all(d["run_id"] == run_id and d["proposal"] is None for d in by_date.values())
    # the golden week delivers Monday 19:00–21:00: Monday is a store run, Tue–Sun arrive
    assert by_date[mon.isoformat()]["groceries"]["coverage"] == "store_run"
    tue = by_date[(mon + timedelta(days=1)).isoformat()]["groceries"]
    assert tue["coverage"] == "arriving" and tue["label"] == "arriving Mon 19:00"
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
    assert tue["run_id"] == run_id  # the swap sheet still acts on the run that covers it
