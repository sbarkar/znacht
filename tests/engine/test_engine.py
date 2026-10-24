"""The engine end to end on the memory adapters: plan, brief, lists, apply, status."""

from __future__ import annotations

import asyncio
from datetime import date

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
