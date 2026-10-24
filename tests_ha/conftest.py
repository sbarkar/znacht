"""Home Assistant tests run in their own environment (make test-ha): HA needs Python 3.13
and pins that do not mix with the engine's workspace."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]

STATUS = {
    "run_id": 7,
    "plan_status": "needs_approval",
    "busy": None,
    "week": "2026-10-26",
    "theme": "Cosy Autumn Week",
    "basket_total": "125.60",
    "basket_subtotal": "105.60",
    "minimum_order": "99.00",
    "meets_minimum": True,
    "shortfall": "0.00",
    "next_delivery": "2026-10-26T19:00:00",
    "next_delivery_end": "2026-10-26T21:00:00",
    "in_store_items": 12,
    "online_items": 17,
    "switches": 1,
    "flags": 2,
    "savings": "0.40",
    "lifetime_savings": "12.30",
    "todays_dinner": "Salmon tray bake",
    "violations": [],
    "brief_url": "http://engine.test/brief/7?token=t",
    "summary": {},
}
LISTS = {
    "online": [
        {
            "uid": "online:p-salmon",
            "summary": "2× Salmon fillet 225 g",
            "description": "salmon",
            "done": False,
        }
    ],
    "in_store": [
        {
            "uid": "in_store:p-bread",
            "summary": "2× Bread sourdough",
            "description": "bread",
            "done": False,
        },
        {
            "uid": "text:dishwasher tabs",
            "summary": "dishwasher tabs",
            "description": "free text",
            "done": True,
        },
    ],
}
CALENDAR = [
    {
        "date": "2026-10-26",
        "slot": "dinner",
        "summary": "Chicken with rice",
        "recipe_id": "memory:chicken-rice",
        "servings": 3,
        "url": None,
        "note": None,
    },
    {
        "date": "2026-10-27",
        "slot": "dinner",
        "summary": "Salmon tray bake",
        "recipe_id": "memory:salmon-tray",
        "servings": 3,
        "url": None,
        "note": "fish night",
    },
]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield



@pytest.fixture
def engine(aioclient_mock):
    base = "http://engine.test:8787"
    aioclient_mock.get(f"{base}/healthz", json={"status": "ok", "version": "test"})
    aioclient_mock.get(f"{base}/api/status", json=STATUS)
    aioclient_mock.get(f"{base}/api/lists", json=LISTS)
    aioclient_mock.get(f"{base}/api/calendar", json=CALENDAR)
    aioclient_mock.post(f"{base}/api/plan_week", json={"accepted": True})
    aioclient_mock.post(f"{base}/api/apply", json={"run_id": 7, "status": "applied"})
    aioclient_mock.post(f"{base}/api/refresh", json={})
    aioclient_mock.post(f"{base}/api/pantry", json={})
    aioclient_mock.post(f"{base}/api/lists/online/done", json={"ok": True})
    aioclient_mock.post(f"{base}/api/lists/in_store/items", json={"ok": True})
    return aioclient_mock
