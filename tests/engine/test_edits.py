"""Editing the whole schedule and the order lock (ADR-0014), on the memory adapters."""

from __future__ import annotations

from datetime import date, timedelta

import httpx

from znacht.domain.diff import ListDiff, ListLineDiff, ShoppingList, ShoppingListLine
from znacht.domain.plan import Meal, MealPlan, MealSlot, Week
from znacht.domain.product import ProductId
from znacht.domain.recipe import RecipeId
from znacht_engine.edits import rebase_list
from znacht_engine.service import ZnachtService, next_monday


def _meal(day: date, recipe: str, servings: int = 3) -> Meal:
    return Meal(
        date=day,
        slot=MealSlot.DINNER,
        recipe_id=RecipeId(source="memory", external_id=recipe),
        servings=servings,
    )


async def _put_in_my_week(service: ZnachtService, *meals: Meal) -> None:
    for m in meals:
        week = Week.containing(m.date)
        current = await service.adapters.sink.read_week(week)
        plan = MealPlan(week=week, meals=(*current.meals, m))
        await service.adapters.sink.apply(await service.adapters.sink.diff(plan))
    service.forget_live_reads()


async def _my_week(service: ZnachtService, mon: date) -> dict[date, set[str]]:
    plan = await service.adapters.sink.read_week(Week(start=mon))
    out: dict[date, set[str]] = {}
    for m in plan.meals:
        out.setdefault(m.date, set()).add(m.recipe_id.key)
    return out


async def _lists(service: ZnachtService) -> dict[str, dict[str, int]]:
    out = {}
    for list_id in ("list-online", "list-store"):
        lst = await service.adapters.store.read_list(list_id)
        out[list_id] = {k: line.quantity for k, line in lst.as_dict().items()}
    return out


async def _applied_week(client: httpx.AsyncClient, service: ZnachtService) -> tuple[date, int]:
    mon = next_monday()
    run_id, _ = await service.plan_week(mon)
    assert (await client.post(f"/api/apply?run_id={run_id}")).json()["status"] == "applied"
    return mon, run_id


def _writes(service: ZnachtService) -> tuple[int, int]:
    return len(service.adapters.sink.applied), len(service.adapters.store.applied)


def test_rebase_keeps_the_households_lines_and_quantities():
    p = lambda pid, q: ShoppingListLine(product_id=ProductId(pid), quantity=q)  # noqa: E731
    t = lambda text: ShoppingListLine(text=text)  # noqa: E731
    live = ShoppingList(id="l", lines=(p("a", 3), p("b", 1), p("mine", 2), t("candles"), t("x")))
    before = ShoppingList(id="l", lines=(p("a", 2), p("b", 1), t("x")))
    after = ShoppingList(id="l", lines=(p("a", 1), p("c", 2), t("y")))
    target = {line.key: line.quantity for line in rebase_list(live, before, after).lines}
    # a: 3 on the list (1 added by hand) - 2 sent + 1 now; b gone; mine and candles untouched
    assert target == {"p:a": 2, "p:mine": 2, "t:candles": 1, "p:c": 2, "t:y": 1}


async def test_swap_a_sent_dinner_previews_confirms_and_undoes(
    client: httpx.AsyncClient, service: ZnachtService
):
    mon, run_id = await _applied_week(client, service)
    tue = mon + timedelta(days=1)
    # the household adds its own line to the store run list in the Migros app
    await service.adapters.store.apply_list(
        "list-store",
        ListDiff(
            list_id="list-store",
            lines=(ListLineDiff(op="add", line=ShoppingListLine(text="candles")),),
        ),
    )
    week_before, lists_before = await _my_week(service, mon), await _lists(service)
    writes = _writes(service)

    alts = (await client.get(f"/api/days/{tue}/alternatives")).json()
    assert alts and all(a["recipe_id"] not in week_before[tue] for a in alts)
    pick = alts[0]
    r = await client.post(
        "/api/edits", json={"kind": "swap", "date": tue.isoformat(), "recipe_id": pick["recipe_id"]}
    )
    assert r.status_code == 200, r.text
    preview = r.json()
    # the confirm shows exactly what changes in My Week: one day, one out, one in
    assert [c["date"] for c in preview["my_week"]["remove"]] == [tue.isoformat()]
    assert [c["recipe_id"] for c in preview["my_week"]["add"]] == [pick["recipe_id"]]
    assert preview["title"].startswith(f"Tue {tue.day}: ") and "→" in preview["title"]
    assert set(preview["lists"]) == {"online", "in_store"}
    # a preview writes nothing, and is not a proposal or a run to show
    assert _writes(service) == writes
    assert await _lists(service) == lists_before
    tl = (await client.get(f"/api/timeline?from={mon}&days=7")).json()
    assert tl["weeks"][0]["awaiting_run_id"] is None
    assert preview["run_id"] not in [x["id"] for x in (await client.get("/api/runs")).json()]

    edit_id = preview["run_id"]
    r = await client.post(f"/api/edits/{edit_id}/confirm")
    assert r.status_code == 200 and r.json()["status"] == "applied"
    after = await _my_week(service, mon)
    assert after[tue] == {pick["recipe_id"]}
    assert {d: v for d, v in after.items() if d != tue} == {
        d: v for d, v in week_before.items() if d != tue
    }
    lists_after = await _lists(service)
    assert lists_after["list-store"]["t:candles"] == 1  # the household's line stays
    tl = (await client.get(f"/api/timeline?from={mon}&days=7")).json()
    by_date = {d["date"]: d for d in tl["days"]}
    assert by_date[tue.isoformat()]["dinner"]["source"] == edit_id
    assert by_date[tue.isoformat()]["dinner"]["edited"] is True
    assert by_date[mon.isoformat()]["dinner"]["source"] == run_id  # untouched days keep theirs
    assert by_date[tue.isoformat()]["groceries"]["coverage"] in ("arriving", "store_run")
    assert tl["weeks"][0]["applied_run_id"] == edit_id
    runs = (await client.get("/api/runs")).json()
    assert next(x for x in runs if x["id"] == edit_id)["edit"] == preview["title"]

    # undo is the existing revert: My Week and both lists are as they were
    r = await client.post(f"/api/runs/{edit_id}/revert")
    assert r.status_code == 200 and r.json()["status"] == "reverted"
    assert await _my_week(service, mon) == week_before
    assert await _lists(service) == lists_before


async def test_edits_on_hand_made_days_add_move_remove(
    client: httpx.AsyncClient, service: ZnachtService
):
    mon = next_monday()
    wed, fri = mon + timedelta(days=2), mon + timedelta(days=4)
    await _put_in_my_week(service, _meal(wed, "omelette"))
    lists_before = await _lists(service)

    async def edit(**body: str) -> dict:
        r = await client.post("/api/edits", json=body)
        assert r.status_code == 200, r.text
        preview = r.json()
        c = await client.post(f"/api/edits/{preview['run_id']}/confirm")
        assert c.status_code == 200, c.text
        return preview

    # swapping a hand-made dinner adds the new dinner's groceries and removes nothing
    p = await edit(kind="swap", date=wed.isoformat(), recipe_id="memory:veg-pasta")
    assert [c["recipe_id"] for c in p["my_week"]["remove"]] == ["memory:omelette"]
    changed = p["lists"]["online"] + p["lists"]["in_store"]
    assert changed and all(c["op"] == "add" for c in changed)
    assert (await _my_week(service, mon)) == {wed: {"memory:veg-pasta"}}
    assert await _lists(service) != lists_before

    # add on an empty day
    await edit(kind="add", date=fri.isoformat(), recipe_id="memory:lentil-dal")
    assert (await _my_week(service, mon)) == {
        wed: {"memory:veg-pasta"},
        fri: {"memory:lentil-dal"},
    }
    # moving onto a day with a dinner swaps the two
    p = await edit(kind="move", date=wed.isoformat(), to=fri.isoformat())
    assert "swap with Fri" in p["title"]
    assert (await _my_week(service, mon)) == {
        wed: {"memory:lentil-dal"},
        fri: {"memory:veg-pasta"},
    }
    # remove
    p = await edit(kind="remove", date=fri.isoformat())
    assert p["my_week"]["add"] == []
    assert (await _my_week(service, mon)) == {wed: {"memory:lentil-dal"}}

    # what cannot be done is said, and nothing is written
    writes = _writes(service)
    bad = [
        {"kind": "add", "date": wed.isoformat(), "recipe_id": "memory:omelette"},
        {"kind": "remove", "date": fri.isoformat()},
        {"kind": "move", "date": wed.isoformat(), "to": (mon + timedelta(days=8)).isoformat()},
        {
            "kind": "swap",
            "date": (mon - timedelta(days=7)).isoformat(),
            "recipe_id": "memory:omelette",
        },
        {"kind": "explode", "date": wed.isoformat()},
    ]
    for body in bad:
        assert (await client.post("/api/edits", json=body)).status_code == 422, body
    assert _writes(service) == writes


async def test_a_change_in_my_week_after_the_preview_is_never_overwritten(
    client: httpx.AsyncClient, service: ZnachtService
):
    mon = next_monday()
    thu = mon + timedelta(days=3)
    await _put_in_my_week(service, _meal(thu, "omelette"))
    preview = (
        await client.post(
            "/api/edits",
            json={"kind": "swap", "date": thu.isoformat(), "recipe_id": "memory:veg-pasta"},
        )
    ).json()
    # meanwhile, in the Thermomix app, Thursday becomes a ragu
    await service.adapters.sink.apply(
        await service.adapters.sink.diff(
            MealPlan(week=Week(start=mon), meals=(_meal(thu, "beef-ragu"),))
        )
    )
    writes = _writes(service)
    r = await client.post(f"/api/edits/{preview['run_id']}/confirm")
    assert r.status_code == 409 and "My Week changed" in r.json()["detail"]
    assert _writes(service) == writes

    # a discarded preview is gone for good
    assert (await client.delete(f"/api/edits/{preview['run_id']}")).status_code == 200
    assert (await client.post(f"/api/edits/{preview['run_id']}/confirm")).status_code == 409


async def test_a_preview_priced_before_another_confirmed_edit_is_refused(
    client: httpx.AsyncClient, service: ZnachtService
):
    mon, _ = await _applied_week(client, service)
    tue, thu = (mon + timedelta(days=i) for i in (1, 3))
    first = (
        await client.post("/api/edits", json={"kind": "remove", "date": tue.isoformat()})
    ).json()
    second = (
        await client.post("/api/edits", json={"kind": "remove", "date": thu.isoformat()})
    ).json()
    assert (await client.post(f"/api/edits/{first['run_id']}/confirm")).status_code == 200
    writes = _writes(service)
    r = await client.post(f"/api/edits/{second['run_id']}/confirm")
    assert r.status_code == 409 and "another change" in r.json()["detail"]
    assert _writes(service) == writes


async def test_a_proposal_planned_before_a_change_cannot_overwrite_it(
    client: httpx.AsyncClient, service: ZnachtService
):
    mon = next_monday()
    run_id, _ = await service.plan_week(mon)
    await _put_in_my_week(service, _meal(mon + timedelta(days=1), "omelette"))
    writes = _writes(service)
    r = await client.post(f"/api/apply?run_id={run_id}")
    assert r.status_code == 409 and "plan this week again" in r.json()["detail"]
    assert _writes(service) == writes


async def test_ordered_days_are_locked_with_the_reason(
    client: httpx.AsyncClient, service: ZnachtService
):
    mon, run_id = await _applied_week(client, service)
    offer = (await client.get(f"/api/runs/{run_id}/order")).json()
    assert offer["order"] is None and offer["suggested"]
    assert set(offer["suggested"]) <= {d["date"] for d in offer["days"]}

    writes = _writes(service)
    ordered = [(mon + timedelta(days=i)).isoformat() for i in (1, 2, 3)]
    r = await client.post("/api/orders", json={"run_id": run_id, "dates": ordered})
    assert r.status_code == 200
    order = r.json()
    assert order["dates"] == ordered and order["source"] == "household"
    assert "Groceries ordered" in order["lock_reason"]
    assert _writes(service) == writes  # recording an order writes nothing outside the engine

    tl = (await client.get(f"/api/timeline?from={mon}&days=7")).json()
    by_date = {d["date"]: d for d in tl["days"]}
    for d in ordered:
        assert by_date[d]["ordered"] and not by_date[d]["editable"]
        assert by_date[d]["groceries"]["coverage"] == "ordered"
        assert by_date[d]["lock_reason"] == order["lock_reason"]
    assert by_date[mon.isoformat()]["editable"] and not by_date[mon.isoformat()]["ordered"]
    assert "ordered Tue–Thu" in tl["weeks"][0]["summary"]
    assert all(
        c["ordered"] == (c["date"] in ordered)
        for c in (await client.get("/api/calendar")).json()
        if c["date"] in by_date
    )

    # the engine refuses, not only the app: edit, move onto, and undoing the run
    tue = ordered[0]
    for body in (
        {"kind": "swap", "date": tue, "recipe_id": "memory:omelette"},
        {"kind": "move", "date": mon.isoformat(), "to": tue},
    ):
        r = await client.post("/api/edits", json=body)
        assert r.status_code == 409 and "Groceries ordered" in r.json()["detail"], body
    r = await client.post(f"/api/runs/{run_id}/revert")
    assert r.status_code == 409 and "Groceries ordered" in r.json()["detail"]
    assert _writes(service) == writes

    # a day the order does not cover stays editable
    sun = (mon + timedelta(days=6)).isoformat()
    assert (
        await client.post("/api/edits", json={"kind": "remove", "date": sun})
    ).status_code == 200

    # not ordered after all: the days open again
    assert (await client.delete(f"/api/orders/{order['id']}")).status_code == 200
    assert (await client.get("/api/orders")).json() == []
    r = await client.post("/api/edits", json={"kind": "remove", "date": tue})
    assert r.status_code == 200, r.text


async def test_only_sent_groceries_can_be_ordered(
    client: httpx.AsyncClient, service: ZnachtService
):
    run_id, _ = await service.plan_week(next_monday())
    r = await client.post("/api/orders", json={"run_id": run_id})
    assert r.status_code == 422


async def test_recipe_search_respects_the_hard_rules(
    client: httpx.AsyncClient, service: ZnachtService
):
    mon = next_monday()
    found = (await client.get(f"/api/recipes/search?q=salmon&day={mon}")).json()
    assert found and all("salmon" in f["title"].lower() for f in found)
    assert (await client.get("/api/recipes/search?q=s")).status_code == 422
