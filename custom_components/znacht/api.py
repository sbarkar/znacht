"""Thin async client for the Znacht engine. No business logic lives here."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientSession


class ZnachtApiError(Exception):
    pass


class ZnachtApi:
    def __init__(self, session: ClientSession, url: str, token: str | None) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}

    async def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        async with self._session.request(
            method, f"{self._url}{path}", headers=self._headers, **kwargs
        ) as resp:
            if resp.status >= 400:
                raise ZnachtApiError(f"{method} {path} -> {resp.status}: {await resp.text()}")
            text = await resp.text()
            if not text:
                return None
            try:
                return await resp.json(content_type=None)
            except ValueError:
                return text

    async def health(self) -> dict[str, Any]:
        return await self._call("GET", "/healthz")

    async def status(self) -> dict[str, Any]:
        return await self._call("GET", "/api/status")

    async def lists(self) -> dict[str, list[dict[str, Any]]]:
        return await self._call("GET", "/api/lists")

    async def calendar(self) -> list[dict[str, Any]]:
        return await self._call("GET", "/api/calendar")

    async def timeline(self, days: int = 14) -> dict[str, Any]:
        return await self._call("GET", "/api/timeline", params={"days": days})

    async def plan_week(self, week: str | None = None) -> Any:
        return await self._call("POST", "/api/plan_week", json={"week": week} if week else None)

    async def optimize(self) -> Any:
        return await self._call("POST", "/api/optimize_products")

    async def apply(self, run_id: int | None = None) -> Any:
        return await self._call("POST", "/api/apply", params={"run_id": run_id} if run_id else None)

    async def refresh(self) -> Any:
        return await self._call("POST", "/api/refresh")

    async def pantry(self, items: dict[str, str]) -> Any:
        return await self._call("POST", "/api/pantry", json={"items": items})

    async def todo_done(self, kind: str, uid: str, done: bool) -> Any:
        return await self._call("POST", f"/api/lists/{kind}/done", json={"uid": uid, "done": done})

    async def todo_add(self, kind: str, summary: str) -> Any:
        return await self._call("POST", f"/api/lists/{kind}/items", json={"summary": summary})
