from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.znacht.const import DOMAIN
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
    calls = [(m, str(u)) for m, u, *_ in engine.mock_calls]
    assert ("POST", "http://engine.test:8787/api/plan_week") in calls
    assert ("POST", "http://engine.test:8787/api/apply?run_id=7") in calls
    assert ("POST", "http://engine.test:8787/api/pantry") in calls


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
    assert result["data"] == {"url": ENTRY["url"], "token": "made-by-the-addon", "addon": True}


async def test_a_new_addon_token_updates_the_existing_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY, unique_id=ENTRY["url"])
    entry.add_to_hass(hass)
    with patch("custom_components.znacht.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "hassio"}, data=_discovery("fresh")
        )
    assert result["type"] == "abort" and result["reason"] == "already_configured"
    assert entry.data["token"] == "fresh" and entry.data["addon"] is True


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
