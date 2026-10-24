"""A request guard every HTTP adapter must use. It refuses, before the request leaves,
anything that looks like checkout, ordering, payment or slot booking."""

from __future__ import annotations

import re
from typing import Final

import httpx

FORBIDDEN_PATH_TOKENS: Final = (
    "checkout",
    "order",
    "orders",
    "payment",
    "payments",
    "pay",
    "purchase",
    "purchases",
    "book",
    "booking",
    "reserve",
)
_WRITE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_ALWAYS_FORBIDDEN: Final = frozenset({"checkout", "payment", "payments", "pay", "purchase"})
_SPLIT = re.compile(r"[/._-]")


class ForbiddenRequest(RuntimeError):
    """Raised when an adapter tries to reach a checkout, order or payment endpoint."""


def is_forbidden(method: str, url: str | httpx.URL) -> bool:
    """Writes to order/booking paths and any request to checkout/payment paths are forbidden.
    Reading order history with GET stays allowed."""
    path = httpx.URL(str(url)).path.lower()
    tokens = {t for t in _SPLIT.split(path) if t}
    if tokens & _ALWAYS_FORBIDDEN:
        return True
    return method.upper() in _WRITE_METHODS and bool(tokens & set(FORBIDDEN_PATH_TOKENS))


def assert_allowed(method: str, url: str | httpx.URL) -> None:
    if is_forbidden(method, url):
        raise ForbiddenRequest(f"refusing {method.upper()} {url}: Znacht never orders or pays")


async def _guard(request: httpx.Request) -> None:
    assert_allowed(request.method, request.url)


def guarded_async_client(**kwargs: object) -> httpx.AsyncClient:
    """An ``httpx.AsyncClient`` that raises :class:`ForbiddenRequest` for forbidden requests."""
    hooks = dict(kwargs.pop("event_hooks", {}) or {})  # type: ignore[call-overload]
    hooks["request"] = [_guard, *hooks.get("request", [])]
    return httpx.AsyncClient(event_hooks=hooks, **kwargs)  # type: ignore[arg-type]
