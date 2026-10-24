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
        "source": 7,
        "proposed": False,
    },
    {
        "date": "2026-10-27",
        "slot": "dinner",
        "summary": "Salmon tray bake",
        "recipe_id": "memory:salmon-tray",
        "servings": 3,
        "url": None,
        "note": "fish night",
        "source": 7,
        "proposed": False,
    },
    {
        "date": "2026-10-28",
        "slot": "dinner",
        "summary": "Omelette with salad",
        "recipe_id": "cookidoo:r123",
        "servings": 3,
        "url": "https://cookidoo.ch/recipes/recipe/de-CH/r123",
        "note": None,
        "source": "manual",
        "proposed": False,
    },
    {
        "date": "2026-10-29",
        "slot": "dinner",
        "summary": "Lentil dal",
        "recipe_id": "memory:lentil-dal",
        "servings": 3,
        "url": None,
        "note": None,
        "source": 8,
        "proposed": True,
    },
]
TIMELINE = {
    "from": "2026-10-26",
    "horizon": 14,
    "today": "2026-10-26",
    "weeks": [
        {
            "week": "2026-10-26",
            "label": "This week",
            "applied_run_id": 7,
            "awaiting_run_id": 8,
            "awaiting_status": "needs_approval",
            "my_week_ok": True,
            "locked_dates": ["2026-10-26", "2026-10-27", "2026-10-28"],
            "summary": "3 of 7 planned · 1 proposed (run 8 awaits approval)",
        }
    ],
    "days": [],
    "unplanned_dates": ["2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"],
    "empty_dates": ["2026-10-30", "2026-10-31", "2026-11-01"],
    "proposed_dates": ["2026-10-29"],
    "busy": None,
}


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
    aioclient_mock.get(f"{base}/api/timeline?days=14", json=TIMELINE)
    aioclient_mock.post(f"{base}/api/plan_week", json={"accepted": True})
    aioclient_mock.post(f"{base}/api/apply", json={"run_id": 7, "status": "applied"})
    aioclient_mock.post(f"{base}/api/refresh", json={})
    aioclient_mock.post(f"{base}/api/pantry", json={})
    aioclient_mock.post(f"{base}/api/lists/online/done", json={"ok": True})
    aioclient_mock.post(f"{base}/api/lists/in_store/items", json={"ok": True})
    return aioclient_mock
