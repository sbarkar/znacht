"""Build the adapters the settings ask for. Memory fakes by default, live adapters by name."""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from znacht.ports import GroceryStore, MealPlanSink, PlannerProvider, RecipeSource
from znacht_engine.config import EngineSettings
from znacht_engine.repo import Repo


@dataclass
class Adapters:
    recipes: RecipeSource
    store: GroceryStore
    sink: MealPlanSink
    planner: PlannerProvider
    stack: AsyncExitStack

    async def close(self) -> None:
        await self.stack.aclose()


async def build_adapters(settings: EngineSettings, repo: Repo) -> Adapters:
    stack = AsyncExitStack()
    recipes: Any
    sink: Any
    store: Any
    planner: Any

    if settings.recipe_source == "cookidoo" or settings.sink == "cookidoo":
        from znacht_cookidoo import (
            CookidooMealPlanSink,
            CookidooRecipeSource,
            CookidooSession,
            CookidooSettings,
        )

        cs = CookidooSettings.from_env()
        session = await stack.enter_async_context(CookidooSession(cs))
        assert session.client is not None
        cookidoo_recipes = CookidooRecipeSource(session.client, locale=cs.language)
        cookidoo_sink = CookidooMealPlanSink(session.client)
    else:
        cookidoo_recipes = None
        cookidoo_sink = None

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
        from znacht_llm_anthropic import AnthropicPlanner

        planner = AnthropicPlanner()
    else:
        from znacht.planner import RuleBasedPlanner

        planner = RuleBasedPlanner()

    return Adapters(recipes=recipes, store=store, sink=sink, planner=planner, stack=stack)
