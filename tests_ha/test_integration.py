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
