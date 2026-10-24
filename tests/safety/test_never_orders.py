"""Znacht never checks out, pays or places an order. These tests make that structural."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import httpx
import pytest

from znacht.domain.plan import MealPlan, Week
from znacht.domain.shopping import ShoppingPlan
from znacht.http import ForbiddenRequest, assert_allowed, guarded_async_client, is_forbidden
from znacht.ports.stores import GroceryStore
from znacht.services.pipeline import PlanStatus, WeekResult, apply_week
from znacht.testing.contracts import FORBIDDEN_METHOD_NAMES
from znacht_memory import MemoryMealPlanSink
from znacht_memory.fixtures import grocery_store

PACKAGES = Path(__file__).resolve().parents[2] / "packages"


def _defined_names() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in PACKAGES.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                found.add((node.name, str(path.relative_to(PACKAGES))))
    return found


def test_no_package_defines_a_checkout_order_or_payment_function():
    offenders = {(n, p) for n, p in _defined_names() if n in FORBIDDEN_METHOD_NAMES}
    assert not offenders, offenders


def test_grocery_store_port_has_no_forbidden_method():
    assert not (set(dir(GroceryStore)) & FORBIDDEN_METHOD_NAMES)


@pytest.mark.parametrize(
    ("method", "url", "forbidden"),
    [
        ("POST", "https://shop.example/api/checkout", True),
        ("GET", "https://shop.example/api/checkout", True),
        ("POST", "https://shop.example/api/orders", True),
        ("GET", "https://shop.example/api/orders", False),  # reading history is fine
        ("POST", "https://shop.example/api/payment/start", True),
        ("POST", "https://shop.example/slots/book", True),
        ("PUT", "https://shop.example/shopping-list/public/v1/lists/123/items", False),
        ("POST", "https://shop.example/onesearch/public/v5/search", False),
    ],
)
def test_request_guard(method, url, forbidden):
    assert is_forbidden(method, url) is forbidden
    if forbidden:
        with pytest.raises(ForbiddenRequest):
            assert_allowed(method, url)


async def test_guarded_client_refuses_before_sending():
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200)

    async with guarded_async_client(transport=httpx.MockTransport(handler)) as client:
        await client.get("https://shop.example/api/products")
        with pytest.raises(ForbiddenRequest):
            await client.post("https://shop.example/api/checkout")
    assert sent == ["https://shop.example/api/products"]


async def test_apply_requires_explicit_approval(household):
    week = Week(start=date(2026, 10, 26))
    result = WeekResult(
        status=PlanStatus.NEEDS_APPROVAL,
        household_id=household.id,
        week=week,
        plan=MealPlan(week=week),
        shopping=ShoppingPlan(slot=None),
    )
    with pytest.raises(PermissionError):
        await apply_week(result, store=grocery_store(), sink=MemoryMealPlanSink(), approved=False)
    draft = result.model_copy(update={"status": PlanStatus.DRAFT})
    with pytest.raises(ValueError):
        await apply_week(draft, store=grocery_store(), sink=MemoryMealPlanSink(), approved=True)
