"""HTTP surface: a small JSON API for the Home Assistant integration and the Brief page."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel

from znacht import __version__
from znacht_engine.config import EngineSettings
from znacht_engine.ha import HaNotifier
from znacht_engine.repo import Repo
from znacht_engine.service import ZnachtService
from znacht_engine.wiring import build_adapters

_TEMPLATES = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=select_autoescape(["html"]),
)


class PlanRequest(BaseModel):
    week: date | None = None


class PantryRequest(BaseModel):
    items: dict[str, str]


class TodoUpdate(BaseModel):
    uid: str
    done: bool


class TodoAdd(BaseModel):
    summary: str


class SwapRequest(BaseModel):
    date: date
    recipe_id: str


class LockRequest(BaseModel):
    date: date
    locked: bool = True


class MoveRequest(BaseModel):
    need: str
    to: str  # "online" | "store"


_STATIC = Path(__file__).parent / "static"


def create_app(settings: EngineSettings, service: ZnachtService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if service is None:
            repo = Repo(settings.data_dir / "znacht.sqlite")
            adapters = await build_adapters(settings, repo)
            notifier = (
                HaNotifier(settings.ha_url, settings.ha_token, settings.ha_notify_service)
                if settings.ha_url and settings.ha_token and settings.ha_notify_service
                else None
            )
            app.state.service = ZnachtService(settings, repo, adapters, notifier)
        else:
            app.state.service = service
        app.state.service.load_recipe_cache()
        try:
            yield
        finally:
            if service is None:
                await app.state.service.adapters.close()

    app = FastAPI(title="Znacht engine", version=__version__, lifespan=lifespan)

    def svc(request: Request) -> ZnachtService:
        return request.app.state.service  # type: ignore[no-any-return]

    def auth(request: Request, token: str | None = Query(default=None)) -> None:
        if not settings.api_token:
            return
        header = request.headers.get("authorization", "")
        presented = (
            header.removeprefix("Bearer ").strip() or token or request.cookies.get("znacht_token")
        )
        if presented != settings.api_token:
            raise HTTPException(status_code=401, detail="bad or missing token")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/status", dependencies=[Depends(auth)])
    async def status(s: ZnachtService = Depends(svc)) -> dict[str, Any]:
        return s.status()

    @app.post("/api/plan_week", dependencies=[Depends(auth)])
    async def plan_week(
        body: PlanRequest | None = None, s: ZnachtService = Depends(svc)
    ) -> dict[str, Any]:
        if s.busy:
            raise HTTPException(status_code=409, detail=f"engine is {s.busy}")
        week = body.week if body else None

        async def run() -> None:
            try:
                await s.plan_week(week)
            except Exception as exc:
                s.repo.set("last_error", str(exc))

        asyncio.get_running_loop().create_task(run())
        return {"accepted": True, "status": "planning"}

    @app.post("/api/optimize_products", dependencies=[Depends(auth)])
    async def optimize(s: ZnachtService = Depends(svc)) -> dict[str, Any]:
        # Re-running the pipeline re-splits and re-optimises; the plan is re-proposed from the
        # same candidates. A plan-preserving optimise pass is a follow-up.
        if s.busy:
            raise HTTPException(status_code=409, detail=f"engine is {s.busy}")
        asyncio.get_running_loop().create_task(s.plan_week())
        return {"accepted": True, "status": "planning"}

    @app.post("/api/apply", dependencies=[Depends(auth)])
    async def apply(run_id: int | None = None, s: ZnachtService = Depends(svc)) -> dict[str, Any]:
        try:
            rid, result = await s.apply(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"run_id": rid, "status": str(result.status), "notes": list(result.notes)}

    @app.get("/api/household", dependencies=[Depends(auth)])
    async def household(s: ZnachtService = Depends(svc)) -> dict[str, Any]:
        return s.household_view()

    @app.get("/api/view", dependencies=[Depends(auth)])
    async def view_latest(s: ZnachtService = Depends(svc)) -> dict[str, Any]:
        try:
            return s.view(None)
        except LookupError:
            return {"run_id": None, "status": "idle", "busy": s.busy}

    @app.get("/api/runs/{run_id}/view", dependencies=[Depends(auth)])
    async def view_run(run_id: int, s: ZnachtService = Depends(svc)) -> dict[str, Any]:
        try:
            return s.view(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/alternatives", dependencies=[Depends(auth)])
    async def alternatives(
        run_id: int, day: date, s: ZnachtService = Depends(svc)
    ) -> list[dict[str, Any]]:
        try:
            return s.alternatives(run_id, day)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _busy_guard(s: ZnachtService) -> None:
        if s.busy:
            raise HTTPException(status_code=409, detail=f"engine is {s.busy}")

    @app.post("/api/runs/{run_id}/swap", dependencies=[Depends(auth)])
    async def swap(
        run_id: int, body: SwapRequest, s: ZnachtService = Depends(svc)
    ) -> dict[str, Any]:
        _busy_guard(s)
        new_id, _ = await s.swap(run_id, body.date, body.recipe_id)
        return s.view(new_id)

    @app.post("/api/runs/{run_id}/lock", dependencies=[Depends(auth)])
    async def lock(
        run_id: int, body: LockRequest, s: ZnachtService = Depends(svc)
    ) -> dict[str, Any]:
        rid, _ = await s.set_lock(run_id, body.date, body.locked)
        return s.view(rid)

    @app.post("/api/runs/{run_id}/move", dependencies=[Depends(auth)])
    async def move(
        run_id: int, body: MoveRequest, s: ZnachtService = Depends(svc)
    ) -> dict[str, Any]:
        _busy_guard(s)
        if body.to not in ("online", "store"):
            raise HTTPException(status_code=422, detail="to must be 'online' or 'store'")
        new_id, _ = await s.move(run_id, body.need, body.to)
        return s.view(new_id)

    @app.post("/api/runs/{run_id}/replan", dependencies=[Depends(auth)])
    async def replan(run_id: int, s: ZnachtService = Depends(svc)) -> dict[str, Any]:
        _busy_guard(s)

        async def run() -> None:
            try:
                await s.replan(run_id)
            except Exception as exc:
                s.repo.set("last_error", str(exc))

        asyncio.get_running_loop().create_task(run())
        return {"accepted": True, "status": "planning"}

    @app.get("/app")
    async def app_entry(token: str | None = None) -> Response:
        # the token travels once in the URL (from the HA sidebar link); the app keeps it in
        # local storage and sends it as a bearer header from then on
        return FileResponse(_STATIC / "index.html")

    @app.post("/api/runs/{run_id}/revert", dependencies=[Depends(auth)])
    async def revert(run_id: int, s: ZnachtService = Depends(svc)) -> dict[str, Any]:
        try:
            rid, result = await s.revert(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"run_id": rid, "status": str(result.status), "notes": list(result.notes)}

    @app.post("/api/refresh", dependencies=[Depends(auth)])
    async def refresh(s: ZnachtService = Depends(svc)) -> dict[str, Any]:
        return await s.refresh()

    @app.post("/api/pantry", dependencies=[Depends(auth)])
    async def pantry(body: PantryRequest, s: ZnachtService = Depends(svc)) -> dict[str, str]:
        return s.update_pantry(body.items)

    @app.get("/api/lists", dependencies=[Depends(auth)])
    async def lists(s: ZnachtService = Depends(svc)) -> dict[str, Any]:
        try:
            return s.lists()
        except LookupError:
            return {"online": [], "in_store": []}

    @app.post("/api/lists/{kind}/done", dependencies=[Depends(auth)])
    async def todo_done(
        kind: str, body: TodoUpdate, s: ZnachtService = Depends(svc)
    ) -> dict[str, bool]:
        s.set_done(body.uid, body.done)
        return {"ok": True}

    @app.post("/api/lists/{kind}/items", dependencies=[Depends(auth)])
    async def todo_add(
        kind: str, body: TodoAdd, s: ZnachtService = Depends(svc)
    ) -> dict[str, bool]:
        s.add_free_text(body.summary)
        return {"ok": True}

    @app.get("/api/calendar", dependencies=[Depends(auth)])
    async def calendar(s: ZnachtService = Depends(svc)) -> list[dict[str, Any]]:
        return s.calendar()

    @app.get("/api/runs", dependencies=[Depends(auth)])
    async def runs(s: ZnachtService = Depends(svc)) -> list[dict[str, Any]]:
        return s.repo.runs(s.household().id)

    @app.get("/brief/{run_id}", dependencies=[Depends(auth)])
    async def brief(
        run_id: int, token: str | None = None, s: ZnachtService = Depends(svc)
    ) -> Response:
        if token:
            # move the token out of the URL (and out of access logs) into a cookie
            redirect = RedirectResponse(url=f"/brief/{run_id}", status_code=303)
            redirect.set_cookie(
                "znacht_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30
            )
            return redirect
        try:
            b = s.brief(run_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return HTMLResponse(_TEMPLATES.get_template("brief.html").render(b=b, token=None))

    @app.get("/brief", dependencies=[Depends(auth)])
    async def latest_brief(token: str | None = None, s: ZnachtService = Depends(svc)) -> Response:
        if token:
            redirect = RedirectResponse(url="/brief", status_code=303)
            redirect.set_cookie(
                "znacht_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30
            )
            return redirect
        try:
            b = s.brief(None)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return HTMLResponse(_TEMPLATES.get_template("brief.html").render(b=b, token=None))

    @app.post("/brief/{run_id}/apply", dependencies=[Depends(auth)])
    async def brief_apply(
        run_id: int, token: str | None = None, s: ZnachtService = Depends(svc)
    ) -> RedirectResponse:
        try:
            await s.apply(run_id)
        except (LookupError, PermissionError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        suffix = f"?token={token}" if token else ""
        return RedirectResponse(url=f"/brief/{run_id}{suffix}", status_code=303)

    @app.post("/brief/{run_id}/replan", dependencies=[Depends(auth)])
    async def brief_replan(
        run_id: int, token: str | None = None, s: ZnachtService = Depends(svc)
    ) -> RedirectResponse:
        _, previous = s._run(run_id)
        new_id, _ = await s.plan_week(previous.week.start)
        suffix = f"?token={token}" if token else ""
        return RedirectResponse(url=f"/brief/{new_id}{suffix}", status_code=303)

    app.mount("/app/static", StaticFiles(directory=str(_STATIC)), name="static")
    return app
