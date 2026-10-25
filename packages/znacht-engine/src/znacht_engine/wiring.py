"""Build the adapters the settings ask for. Memory fakes by default, live adapters by name."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, NoReturn

from znacht.ports import GroceryStore, MealPlanSink, PlannerProvider, RecipeSource
from znacht_engine.config import EngineSettings
from znacht_engine.repo import Repo

_LOGGER = logging.getLogger(__name__)


class Unavailable:
    """Stands in for an adapter whose account could not be reached (ADR-0013).

    The engine still starts, so the household can fix the account from Home Assistant; any use
    of the adapter raises the reason, which the app and the integration show.
    """

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason

    def __getattr__(self, attr: str) -> Callable[..., Awaitable[NoReturn]]:
        async def fail(*args: Any, **kwargs: Any) -> NoReturn:
            raise RuntimeError(self.reason)

        return fail


@dataclass
class Adapters:
    recipes: RecipeSource
    store: GroceryStore
    sink: MealPlanSink
    planner: PlannerProvider
    stack: AsyncExitStack
    problems: dict[str, str] = field(default_factory=dict)  # connection -> why it is unavailable

    async def close(self) -> None:
        await self.stack.aclose()


async def build_adapters(settings: EngineSettings, repo: Repo) -> Adapters:
    stack = AsyncExitStack()
    problems: dict[str, str] = {}
    recipes: Any
    sink: Any
    store: Any
    planner: Any
    cookidoo_recipes: Any = None
    cookidoo_sink: Any = None

    if settings.recipe_source == "cookidoo" or settings.sink == "cookidoo":
        from znacht_cookidoo import (
            CookidooMealPlanSink,
            CookidooRecipeSource,
            CookidooSession,
            CookidooSettings,
        )

        try:
            cs = CookidooSettings.from_env()
            session = await stack.enter_async_context(CookidooSession(cs))
            assert session.client is not None
            cookidoo_recipes = CookidooRecipeSource(session.client, locale=cs.language)
            cookidoo_sink = CookidooMealPlanSink(session.client)
        except Exception as exc:  # a wrong password must not stop the engine
            reason = f"Cookidoo login failed: {exc}"
            _LOGGER.warning(reason)
            problems["cookidoo"] = reason
            cookidoo_recipes = Unavailable("cookidoo", reason)
            cookidoo_sink = Unavailable("cookidoo", reason)

    if settings.recipe_source == "cookidoo":
        recipes = cookidoo_recipes
    else:
        from znacht_memory.fixtures import recipe_source

        recipes = recipe_source()

    if settings.sink == "cookidoo":
        sink = cookidoo_sink
    elif settings.sink == "ha-calendar":
        from znacht_memory import MemoryMealPlanSink

        sink = MemoryMealPlanSink()  # the HA calendar entity reads the engine's plan directly
    else:
        from znacht_memory import MemoryMealPlanSink

        sink = MemoryMealPlanSink()

    if settings.store == "migros":
        from znacht_migros import MigrosGroceryStore, MigrosSession, MigrosSettings

        ms = MigrosSettings.from_env()
        msession = await stack.enter_async_context(MigrosSession(ms))
        store = MigrosGroceryStore(
            msession,
            learned_availability=repo.get("migros.learned_availability", {}),
            on_learned=lambda learned: repo.set("migros.learned_availability", learned),
        )
    else:
        from znacht_memory.fixtures import grocery_store

        store = grocery_store()

    if settings.planner == "anthropic":
        import os

        from znacht_llm_anthropic import AnthropicPlanner

        if not os.environ.get("ANTHROPIC_API_KEY"):
            problems["anthropic"] = "Claude needs an API key"
            planner = Unavailable("anthropic", problems["anthropic"])
        else:
            planner = AnthropicPlanner()
    else:
        from znacht.planner import RuleBasedPlanner

        planner = RuleBasedPlanner()

    return Adapters(
        recipes=recipes, store=store, sink=sink, planner=planner, stack=stack, problems=problems
    )
