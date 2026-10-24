from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from pathlib import Path

import httpx
import pytest

from znacht.planner import RuleBasedPlanner
from znacht.ports.notify import PlanEvent
from znacht_engine.app import create_app
from znacht_engine.config import EngineSettings
from znacht_engine.repo import Repo
from znacht_engine.service import ZnachtService
from znacht_engine.wiring import Adapters
from znacht_memory import MemoryMealPlanSink
from znacht_memory.fixtures import grocery_store, recipe_source

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "household.example.yaml"


class RecordingNotifier:
    name = "recording"

    def __init__(self) -> None:
        self.events: list[PlanEvent] = []

    async def notify(self, event: PlanEvent) -> None:
        self.events.append(event)


@pytest.fixture
def settings(tmp_path: Path) -> EngineSettings:
    return EngineSettings(
        household_path=EXAMPLE,
        data_dir=tmp_path,
        api_token="secret",
        public_url="http://engine.test",
    )


@pytest.fixture
def notifier() -> RecordingNotifier:
    return RecordingNotifier()


@pytest.fixture
def service(settings: EngineSettings, notifier: RecordingNotifier) -> ZnachtService:
    adapters = Adapters(
        recipes=recipe_source(),
        store=grocery_store(),
        sink=MemoryMealPlanSink(),
        planner=RuleBasedPlanner(),
        stack=AsyncExitStack(),
    )
    return ZnachtService(settings, Repo(settings.data_dir / "test.sqlite"), adapters, notifier)


@pytest.fixture
async def client(
    settings: EngineSettings, service: ZnachtService
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, service)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://engine.test",
            headers={"Authorization": "Bearer secret"},
        ) as c:
            yield c
