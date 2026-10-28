from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from custom_components.znacht.const import DOMAIN
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

ENTRY = {"url": "http://engine.test:8787", "token": "t"}


async def setup(hass, engine):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY, unique_id=ENTRY["url"])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow_creates_entry(hass):
    api = MagicMock()
    api.health = AsyncMock(return_value={"status": "ok"})
    api.status = AsyncMock(return_value={"plan_status": "idle"})
    with (
        patch("custom_components.znacht.config_flow.ZnachtApi", return_value=api),
        patch("custom_components.znacht.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert result["type"] == "form"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], ENTRY)
        await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["data"] == ENTRY


async def test_entities_reflect_the_engine(hass, engine):
    await setup(hass, engine)
    assert hass.states.get("sensor.znacht_plan_status").state == "needs_approval"
    assert (
        hass.states.get("sensor.znacht_plan_status")
        .attributes["brief_url"]
        .startswith("http://engine.test/brief/7")
    )
    assert hass.states.get("sensor.znacht_online_basket_total").state == "125.60"
    assert hass.states.get("sensor.znacht_minimum_order").state == "met"
    assert hass.states.get("sensor.znacht_tonight_s_dinner").state == "Salmon tray bake"
    assert hass.states.get("todo.znacht_online_basket").state == "1"  # one open item
    assert hass.states.get("todo.znacht_store_run").state == "1"  # dishwasher tabs is done
    calendar = hass.states.get("calendar.znacht_meal_plan")
    assert calendar is not None
    unplanned = hass.states.get("sensor.znacht_unplanned_days")
    assert unplanned.state == "4"
    assert unplanned.attributes["empty_dates"] == ["2026-10-30", "2026-10-31", "2026-11-01"]
    assert unplanned.attributes["proposed_dates"] == ["2026-10-29"]
    assert unplanned.attributes["weeks"][0]["awaiting_run_id"] == 8
    assert unplanned.attributes["weeks"][0]["summary"].startswith("3 of 7 planned")


async def test_calendar_carries_manual_dinners_and_marks_proposals(hass, engine):
    from datetime import UTC, datetime

    await setup(hass, engine)
    entity = hass.data["entity_components"]["calendar"].get_entity("calendar.znacht_meal_plan")
    events = await entity.async_get_events(
        hass,
        datetime(2026, 10, 26, tzinfo=UTC),
        datetime(2026, 11, 2, tzinfo=UTC),
    )
    by_date = {e.start.isoformat(): e for e in events}
    assert by_date["2026-10-28"].summary == "Omelette with salad"
    assert "yours in My Week" in by_date["2026-10-28"].description
    assert by_date["2026-10-28"].location.startswith("https://cookidoo.ch/")
    assert by_date["2026-10-29"].summary == "Proposed: Lentil dal"
    assert "proposed by Znacht run 8" in by_date["2026-10-29"].description
    assert "Znacht run 7" in by_date["2026-10-26"].description
    assert "groceries ordered" in by_date["2026-10-27"].description
    assert "groceries ordered" not in by_date["2026-10-26"].description


async def test_unplanned_days_is_unknown_on_an_older_engine(hass, aioclient_mock):
    from tests_ha.conftest import CALENDAR, LISTS, STATUS

    base = "http://engine.test:8787"
    aioclient_mock.get(f"{base}/api/status", json=STATUS)
    aioclient_mock.get(f"{base}/api/lists", json=LISTS)
    aioclient_mock.get(f"{base}/api/calendar", json=CALENDAR)
    aioclient_mock.get(f"{base}/api/timeline?days=14", status=404, text="not found")
    await setup(hass, aioclient_mock)
    assert hass.states.get("sensor.znacht_plan_status").state == "needs_approval"
    assert hass.states.get("sensor.znacht_unplanned_days").state == "unknown"


async def test_services_forward_to_the_engine(hass, engine):
    await setup(hass, engine)
    await hass.services.async_call(DOMAIN, "plan_week", {"week": "2026-10-26"}, blocking=True)
    await hass.services.async_call(DOMAIN, "apply_plan", {"run_id": 7}, blocking=True)
    await hass.services.async_call(
        DOMAIN, "update_pantry", {"items": {"rice": "1 kg"}}, blocking=True
    )
    await hass.services.async_call(
        DOMAIN, "mark_ordered", {"run_id": 7, "dates": ["2026-10-27"]}, blocking=True
    )
    calls = [(m, str(u)) for m, u, *_ in engine.mock_calls]
    assert ("POST", "http://engine.test:8787/api/plan_week") in calls
    assert ("POST", "http://engine.test:8787/api/apply?run_id=7") in calls
    assert ("POST", "http://engine.test:8787/api/pantry") in calls
    assert ("POST", "http://engine.test:8787/api/orders") in calls
    body = next(d for m, u, d, *_ in engine.mock_calls if str(u).endswith("/api/orders"))
    assert body == {"run_id": 7, "dates": ["2026-10-27"]}


async def test_open_findings_sensor_and_reconcile_service(hass, engine):
    await setup(hass, engine)
    sensor = hass.states.get("sensor.znacht_open_findings")
    assert sensor.state == "1"
    assert sensor.attributes["findings"] == [
        "carrots: 3 kg bought vs 0.5 kg needed (online 2 kg + in-store 1 kg)"
    ]
    response = await hass.services.async_call(
        DOMAIN,
        "reconcile",
        {"run_id": 7, "overrides": {"surplus:carrots": "carrot cake"}},
        blocking=True,
        return_response=True,
    )
    assert response["open_findings"] == 0
    assert response["findings"][0]["override_reason"] == "carrot cake"
    body = next(d for m, u, d, *_ in engine.mock_calls if str(u).endswith("/api/reconcile"))
    assert body == {"run_id": 7, "fix": [], "overrides": {"surplus:carrots": "carrot cake"}}


async def test_apply_says_why_while_findings_are_open(hass, engine):
    await setup(hass, engine)
    engine.clear_requests()  # the engine now refuses: the reconciliation gate (ADR-0016)
    detail = "1 open reconciliation finding: carrots: 3 kg bought vs 0.5 kg needed"
    engine.post("http://engine.test:8787/api/apply", status=409, json={"detail": detail})
    with pytest.raises(HomeAssistantError, match=r"will not send this plan yet\. 1 open"):
        await hass.services.async_call(DOMAIN, "apply_plan", {"run_id": 7}, blocking=True)


async def test_todo_updates_write_back(hass, engine):
    await setup(hass, engine)
    await hass.services.async_call(
        "todo",
        "update_item",
        {
            "entity_id": "todo.znacht_online_basket",
            "item": "online:p-salmon",
            "status": "completed",
        },
        blocking=True,
    )
    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": "todo.znacht_store_run", "item": "birthday candles"},
        blocking=True,
    )
    calls = [(m, str(u)) for m, u, *_ in engine.mock_calls]
    assert ("POST", "http://engine.test:8787/api/lists/online/done") in calls
    assert ("POST", "http://engine.test:8787/api/lists/in_store/items") in calls


async def test_reconfigure_moves_the_entry_to_a_new_engine(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY, unique_id=ENTRY["url"])
    entry.add_to_hass(hass)
    api = MagicMock()
    api.health = AsyncMock(return_value={"status": "ok"})
    api.status = AsyncMock(return_value={"plan_status": "idle"})
    new = {"url": "http://192.168.4.12:8787", "token": "t"}
    with (
        patch("custom_components.znacht.config_flow.ZnachtApi", return_value=api),
        patch("custom_components.znacht.async_setup_entry", return_value=True),
        patch("custom_components.znacht.async_unload_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "reconfigure"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], new)
        await hass.async_block_till_done()
    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == new
    assert entry.unique_id == new["url"]


def _discovery(token: str = "made-by-the-addon"):
    from homeassistant.helpers.service_info.hassio import HassioServiceInfo

    return HassioServiceInfo(
        config={"url": ENTRY["url"], "token": token},
        name="Znacht",
        slug="abc123_znacht",
        uuid="0123456789abcdef0123456789abcdef",
    )


async def test_the_addon_announces_itself_and_sets_up_with_one_click(hass):
    api = MagicMock()
    api.health = AsyncMock(return_value={"status": "ok"})
    api.status = AsyncMock(return_value={"plan_status": "idle"})
    with (
        patch("custom_components.znacht.config_flow.ZnachtApi", return_value=api),
        patch("custom_components.znacht.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "hassio"}, data=_discovery()
        )
        assert result["type"] == "form" and result["step_id"] == "hassio_confirm"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["data"] == {
        "url": ENTRY["url"],
        "token": "made-by-the-addon",
        "addon": True,
        "addon_slug": "abc123_znacht",
    }


async def test_a_new_addon_token_updates_the_existing_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY, unique_id=ENTRY["url"])
    entry.add_to_hass(hass)
    with patch("custom_components.znacht.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "hassio"}, data=_discovery("fresh")
        )
    assert result["type"] == "abort" and result["reason"] == "already_configured"
    assert entry.data["token"] == "fresh" and entry.data["addon"] is True
    assert entry.data["addon_slug"] == "abc123_znacht"  # so its Configure reaches the add-on


async def test_only_a_separate_engine_gets_the_iframe_panel(hass, engine):
    entry = await setup(hass, engine)
    assert "znacht" in hass.data.get("frontend_panels", {})
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert "znacht" not in hass.data.get("frontend_panels", {})

    addon = MockConfigEntry(
        domain=DOMAIN, data={**ENTRY, "addon": True}, unique_id="addon", entry_id="addon"
    )
    addon.add_to_hass(hass)
    assert await hass.config_entries.async_setup(addon.entry_id)
    await hass.async_block_till_done()
    assert "znacht" not in hass.data.get("frontend_panels", {})


async def _reconfigure(hass, entry, user_input):
    api = MagicMock()
    api.health = AsyncMock(return_value={"status": "ok"})
    api.status = AsyncMock(return_value={"plan_status": "idle"})
    with (
        patch("custom_components.znacht.config_flow.ZnachtApi", return_value=api),
        patch("custom_components.znacht.async_setup_entry", return_value=True),
        patch("custom_components.znacht.async_unload_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
        await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_keeps_the_addon_flag_only_for_the_same_engine(hass):
    addon = {**ENTRY, "addon": True}
    entry = MockConfigEntry(domain=DOMAIN, data=addon, unique_id=ENTRY["url"])
    entry.add_to_hass(hass)
    await _reconfigure(hass, entry, {"url": ENTRY["url"], "token": "new"})
    assert entry.data == {"url": ENTRY["url"], "token": "new", "addon": True}
    # moving to an LXC: a separate engine, so the integration's panel comes back
    lxc = {"url": "http://192.168.1.50:8787", "token": "t"}
    await _reconfigure(hass, entry, lxc)
    assert entry.data == lxc


# -- one install: the integration sets up the add-on itself (ADR-0013) -----------------------

ACCOUNTS = {"cookidoo_email": "a@b.ch", "cookidoo_password": "pw", "migros_email": "a@b.ch"}
ALL_OK = {r: {"name": r, "ok": True, "detail": None} for r in ("recipes", "store", "planner")}


def _engine_api(connections):
    api = MagicMock()
    api.health = AsyncMock(return_value={"status": "ok"})
    api.status = AsyncMock(return_value={"plan_status": "idle"})
    api.connections = AsyncMock(side_effect=connections)
    return api


async def _past_progress(hass, result):
    """The install runs as a progress step; a finished task moves on by itself."""
    if result["type"] == "progress":
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    return result


async def _run_addon_flow(hass, connections):
    from custom_components.znacht.addon import AddonEngine

    engine = AddonEngine(slug="abc123_znacht", url="http://abc123-znacht:8787", token="tok")
    install = AsyncMock(return_value=engine)
    with (
        patch("custom_components.znacht.config_flow.is_hassio", return_value=True),
        patch("custom_components.znacht.config_flow.addon.install_and_start", install),
        patch(
            "custom_components.znacht.config_flow.ZnachtApi",
            return_value=_engine_api(connections),
        ),
        patch("custom_components.znacht.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert result["type"] == "menu" and result["menu_options"] == ["addon", "manual"]
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "addon"}
        )
        assert result["type"] == "form" and result["step_id"] == "addon"
        assert result["description_placeholders"] == {"details": ""}  # the text needs it
        result = await _past_progress(
            hass, await hass.config_entries.flow.async_configure(result["flow_id"], ACCOUNTS)
        )
        results = [result]
        if result["type"] == "form":  # an account failed: fix it and go round again
            result = await _past_progress(
                hass,
                await hass.config_entries.flow.async_configure(
                    result["flow_id"], {**ACCOUNTS, "cookidoo_password": "right"}
                ),
            )
            results.append(result)
        await hass.async_block_till_done()
    return install, results


async def test_run_here_installs_the_addon_and_creates_the_entry(hass):
    install, [result] = await _run_addon_flow(hass, [ALL_OK])
    assert install.await_args.args[1] == ACCOUNTS
    assert result["type"] == "create_entry"
    assert result["data"] == {
        "url": "http://abc123-znacht:8787",
        "token": "tok",
        "addon": True,
        "addon_slug": "abc123_znacht",
    }


async def test_a_rejected_account_goes_back_to_its_field(hass):
    bad = {
        **ALL_OK,
        "recipes": {"name": "cookidoo", "ok": False, "detail": "Cookidoo login failed: 401"},
    }
    install, [first, second] = await _run_addon_flow(hass, [bad, ALL_OK])
    assert first["type"] == "form" and first["step_id"] == "addon"
    assert first["errors"] == {"cookidoo_password": "cookidoo_failed"}
    assert "401" in first["description_placeholders"]["details"]
    assert install.await_count == 2 and install.await_args.args[1]["cookidoo_password"] == "right"
    assert second["type"] == "create_entry"


async def test_without_a_supervisor_setup_asks_for_the_engine(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form" and result["step_id"] == "manual"


def test_accounts_become_addon_options_and_pick_the_adapters():
    from custom_components.znacht.addon import accounts_to_options

    current = {"cookidoo_password": "old", "api_token": "keep", "planner": "anthropic"}
    options = accounts_to_options(current, {"cookidoo_email": "a@b.ch", "cookidoo_password": ""})
    assert options["cookidoo_password"] == "old"  # an empty secret keeps the stored one
    assert options["api_token"] == "keep"
    assert (options["recipe_source"], options["sink"]) == ("cookidoo", "cookidoo")
    assert (options["store"], options["planner"]) == ("memory", "rule_based")


async def test_configure_changes_the_addon_accounts(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY, "addon": True, "addon_slug": "abc123_znacht"},
        unique_id=ENTRY["url"],
    )
    entry.add_to_hass(hass)
    update = AsyncMock()
    with (
        patch("custom_components.znacht.config_flow.addon.update_accounts", update),
        patch(
            "custom_components.znacht.config_flow.addon.addon_options",
            AsyncMock(return_value={"cookidoo_email": "a@b.ch"}),
        ),
        patch("custom_components.znacht.config_flow.asyncio.sleep", AsyncMock()),
        patch("custom_components.znacht.config_flow.ZnachtApi", return_value=_engine_api([ALL_OK])),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] == "form" and result["step_id"] == "init"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"migros_email": "c@d.ch"}
        )
    assert result["type"] == "create_entry"
    assert update.await_args.args[1:] == ("abc123_znacht", {"migros_email": "c@d.ch"})


async def test_configure_picks_the_phone_from_the_companion_apps(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY, "addon": True, "addon_slug": "abc123_znacht"},
        unique_id=ENTRY["url"],
    )
    entry.add_to_hass(hass)
    for service in ("mobile_app_pixel", "mobile_app_ipad", "persistent_notification"):
        hass.services.async_register("notify", service, AsyncMock())
    current = {"cookidoo_email": "a@b.ch", "ha_notify": "mobile_app_old_phone"}
    update = AsyncMock()
    with (
        patch("custom_components.znacht.config_flow.addon.update_accounts", update),
        patch(
            "custom_components.znacht.config_flow.addon.addon_options",
            AsyncMock(return_value=current),
        ),
        patch("custom_components.znacht.config_flow.asyncio.sleep", AsyncMock()),
        patch("custom_components.znacht.config_flow.ZnachtApi", return_value=_engine_api([ALL_OK])),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        field = next(k for k in result["data_schema"].schema if k == "ha_notify")
        # the phones, and the one set now although it is gone; no other notify services
        assert result["data_schema"].schema[field].config["options"] == [
            "mobile_app_ipad",
            "mobile_app_old_phone",
            "mobile_app_pixel",
        ]
        assert field.description == {"suggested_value": "mobile_app_old_phone"}
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"cookidoo_email": "a@b.ch", "ha_notify": "mobile_app_pixel"}
        )
    assert result["type"] == "create_entry"
    assert update.await_args.args[2]["ha_notify"] == "mobile_app_pixel"


def test_the_phone_becomes_the_addons_notify_option():
    from custom_components.znacht.addon import accounts_to_options

    current = {"ha_notify": "mobile_app_old"}
    assert accounts_to_options(current, {"ha_notify": "mobile_app_pixel"})["ha_notify"] == (
        "mobile_app_pixel"
    )
    assert accounts_to_options(current, {})["ha_notify"] == ""  # cleared: no notifications


async def test_configure_on_a_separate_engine_explains_itself(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY, unique_id=ENTRY["url"])
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "abort" and result["reason"] == "not_addon"


async def test_a_fresh_install_puts_the_addon_in_the_sidebar(hass):
    from custom_components.znacht import addon
    from homeassistant.components.hassio import AddonInfo, AddonState

    def info(state):
        return AddonInfo(
            available=True,
            hostname="abc123-znacht",
            options={"api_token": ""},
            state=state,
            update_available=False,
            version="0.1.0",
        )

    manager = MagicMock()
    manager.async_get_addon_info = AsyncMock(
        side_effect=[info(AddonState.NOT_INSTALLED), info(AddonState.NOT_RUNNING)]
    )
    manager.async_install_addon = AsyncMock()
    manager.async_set_addon_options = AsyncMock()
    manager.async_start_addon = AsyncMock()
    client = MagicMock()
    client.addons.set_addon_options = AsyncMock()
    engine = addon.AddonEngine(slug="abc123_znacht", url="http://abc123-znacht:8787", token="t")
    with (
        patch.object(addon, "find_addon_slug", AsyncMock(return_value="abc123_znacht")),
        patch.object(addon, "_manager", return_value=manager),
        patch("homeassistant.components.hassio.get_supervisor_client", return_value=client),
        patch.object(addon, "_wait_for_engine", AsyncMock(return_value=engine)),
    ):
        assert await addon.install_and_start(hass, {"migros_email": "a@b.ch"}) == engine
    manager.async_install_addon.assert_awaited_once()
    sidebar = client.addons.set_addon_options.await_args.args
    assert sidebar[0] == "abc123_znacht"
    assert sidebar[1].ingress_panel is True and sidebar[1].watchdog is True
    options = manager.async_set_addon_options.await_args.args[0]
    assert options["store"] == "migros" and options["recipe_source"] == "memory"
    manager.async_start_addon.assert_awaited_once()


async def test_removing_the_addon_entry_keeps_the_other_entrys_panel(hass, engine):
    lxc = await setup(hass, engine)
    assert "znacht" in hass.data.get("frontend_panels", {})
    addon_entry = MockConfigEntry(
        domain=DOMAIN, data={**ENTRY, "addon": True}, unique_id="addon", entry_id="addon"
    )
    addon_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(addon_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(addon_entry.entry_id)
    assert "znacht" in hass.data.get("frontend_panels", {})  # still the LXC's panel
    assert await hass.config_entries.async_unload(lxc.entry_id)
    assert "znacht" not in hass.data.get("frontend_panels", {})
