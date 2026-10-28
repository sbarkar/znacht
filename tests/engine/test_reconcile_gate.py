"""The reconciliation gate in the engine (ADR-0016): findings in status, view, Brief and the
notification; Approve refused while any is open; fix, override, backup; the live-list check."""

from __future__ import annotations

import httpx

from znacht.domain.diff import ShoppingListLine
from znacht.domain.product import Channel, ProductId
from znacht.services.pipeline import rediff
from znacht_engine.service import ZnachtService
from znacht_memory.fixtures import GOLDEN_WEEK_START, IN_STORE_LIST, ONLINE_LIST


async def _with_extra_backup(service: ZnachtService) -> tuple[int, str]:
    """Plan the golden week, then put the red lentils on the in-store list as well, the way last
    week's carrot backup was added: without taking anything off the online basket."""
    run_id, result = await service.plan_week(GOLDEN_WEEK_START)
    s = result.shopping
    lentils = next(c for c in s.online if c.need_name == "red lentils")
    extra = lentils.model_copy(update={"channel": Channel.STORE, "packs": 2})
    changed = result.model_copy(
        update={"shopping": s.model_copy(update={"in_store": (*s.in_store, extra)})}
    )
    service.repo.update_run(run_id, await rediff(changed, store=service.adapters.store))
    return run_id, str(lentils.product.id)


async def test_a_clean_plan_has_no_findings_and_offers_approve(client, service, notifier):
    run_id, _ = await service.plan_week(GOLDEN_WEEK_START)
    status = (await client.get("/api/status")).json()
    assert status["open_findings"] == 0 and status["findings"] == []
    assert (await client.get(f"/api/runs/{run_id}/view")).json()["findings"] == []
    assert notifier.events[-1].actions == ("approve", "review")
    assert notifier.events[-1].title == "Znacht: plan ready"


async def test_open_findings_block_approve_until_overridden(
    client: httpx.AsyncClient, service: ZnachtService, notifier
):
    run_id, pid = await _with_extra_backup(service)

    status = (await client.get("/api/status")).json()
    assert status["open_findings"] == 2
    assert status["findings"][0].startswith("red lentils: 1.5 kg bought vs ")
    view = (await client.get(f"/api/runs/{run_id}/view")).json()
    assert {f["kind"] for f in view["findings"]} == {"surplus", "cross_list"}
    assert all(f["open"] and f["fixable"] for f in view["findings"])

    # findings first in the notification, above the savings, and no Approve button
    await service._notify_plan(run_id, service.repo.get_run(run_id))
    event = notifier.events[-1]
    assert event.actions == ("review",) and event.title == "Znacht: check the lists"
    assert event.message.startswith("Check 2 before approving: red lentils: 1.5 kg bought")
    assert event.message.index("red lentils") < event.message.index("swap")
    assert event.data["open_findings"] == "2"

    brief = (await client.get(f"/brief/{run_id}")).text
    assert "Check the lists before approving" in brief and "red lentils: 1.5 kg bought" in brief

    refused = await client.post(f"/api/apply?run_id={run_id}")
    assert refused.status_code == 409 and "open reconciliation finding" in refused.json()["detail"]
    assert not service.adapters.store.applied

    ids = [f["id"] for f in view["findings"]]
    r = await client.post(
        "/api/reconcile", json={"run_id": run_id, "overrides": {ids[0]: "lentil week ahead"}}
    )
    assert r.status_code == 200 and r.json()["open_findings"] == 1
    assert (await client.post(f"/api/apply?run_id={run_id}")).status_code == 409
    r = await client.post("/api/reconcile", json={"overrides": {ids[1]: "lentil week ahead"}})
    assert r.json()["open_findings"] == 0
    assert all(f["override_reason"] == "lentil week ahead" for f in r.json()["findings"])
    log = service.repo.overrides_log(run_id)
    assert [row["finding_id"] for row in log] == ids and log[0]["reason"] == "lentil week ahead"

    applied = await client.post(f"/api/apply?run_id={run_id}")
    assert applied.status_code == 200 and applied.json()["status"] == "applied"
    in_store = await service.adapters.store.read_list(IN_STORE_LIST)
    assert next(line for line in in_store.lines if line.product_id == pid).quantity == 2


async def test_fix_adjusts_quantities_and_the_list_diffs(client, service):
    run_id, pid = await _with_extra_backup(service)
    ids = [f["id"] for f in (await client.get(f"/api/runs/{run_id}/view")).json()["findings"]]
    r = await client.post("/api/reconcile", json={"run_id": run_id, "fix": ids})
    assert r.status_code == 200 and r.json()["open_findings"] == 0
    result = service.repo.get_run(run_id)
    lentils = [c for c in result.shopping.lines if c.product.id == pid]
    assert [(c.channel, c.packs) for c in lentils] == [(Channel.STORE, 1)]
    added = {d.line.product_id: d.line.quantity for d in result.in_store_diff.lines}
    assert added[ProductId(pid)] == 1
    assert all(d.line.product_id != pid for d in result.online_diff.lines)
    assert (await client.post(f"/api/apply?run_id={run_id}")).json()["status"] == "applied"


async def test_unknown_findings_and_empty_reasons_are_refused(client, service):
    run_id, _ = await _with_extra_backup(service)
    assert (await client.post("/api/reconcile", json={"fix": ["surplus:nope"]})).status_code == 404
    first = (await client.get(f"/api/runs/{run_id}/view")).json()["findings"][0]["id"]
    r = await client.post("/api/reconcile", json={"overrides": {first: " "}})
    assert r.status_code == 409


async def test_backup_moves_packs_off_the_online_basket(client, service):
    run_id, result = await service.plan_week(GOLDEN_WEEK_START)
    beef = next(c for c in result.shopping.online if c.need_name == "minced beef")
    assert beef.packs == 2
    view = (
        await client.post(f"/api/runs/{run_id}/backup", json={"need": "minced beef", "packs": 1})
    ).json()
    online = [x for x in view["online"] if x["need"] == "minced beef"]
    in_store = [x for x in view["in_store"] if x["need"] == "minced beef"]
    assert [x["packs"] for x in online] == [1] and [x["packs"] for x in in_store] == [1]
    assert view["open_findings"] == 0
    stored = service.repo.get_run(run_id)
    assert {d.line.product_id: d.line.quantity for d in stored.online_diff.lines}[
        beef.product.id
    ] == 1
    assert (
        await client.post(f"/api/runs/{run_id}/backup", json={"need": "nope"})
    ).status_code == 404


async def test_a_sent_plan_is_checked_on_the_live_lists(client, service):
    run_id, result = await service.plan_week(GOLDEN_WEEK_START)
    fish = next(c for c in result.shopping.online if c.need_name == "salmon").product.id
    assert (await client.post(f"/api/apply?run_id={run_id}")).json()["status"] == "applied"
    # someone adds a backup by hand in the store's app, after the plan was sent
    store = service.adapters.store
    online = await store.read_list(ONLINE_LIST)
    salmon = next(line for line in online.lines if line.product_id == fish)
    listed = await store.read_list(IN_STORE_LIST)
    store.seed_list(
        IN_STORE_LIST, (*listed.lines, ShoppingListLine(product_id=salmon.product_id, quantity=4))
    )

    r = (await client.post("/api/reconcile")).json()
    kinds = {f["kind"] for f in r["findings"] if f["open"]}
    assert kinds == {"cross_list", "orphan"}  # a line added by hand traces to no need
    assert all(not f["fixable"] for f in r["findings"])
    assert (await client.get("/api/status")).json()["open_findings"] == r["open_findings"]
    fix = await client.post("/api/reconcile", json={"fix": [r["findings"][0]["id"]]})
    assert fix.status_code == 409
