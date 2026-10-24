"""Adapter discovery through entry points. A new store or recipe source ships as its own
package and registers itself in one of these groups."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Final

RECIPE_SOURCES: Final = "znacht.recipe_sources"
MEAL_PLAN_SINKS: Final = "znacht.meal_plan_sinks"
GROCERY_STORES: Final = "znacht.grocery_stores"
HEALTH_PROFILE_SOURCES: Final = "znacht.health_profile_sources"
PLANNER_PROVIDERS: Final = "znacht.planner_providers"
NOTIFIERS: Final = "znacht.notifiers"

GROUPS: Final = (
    RECIPE_SOURCES,
    MEAL_PLAN_SINKS,
    GROCERY_STORES,
    HEALTH_PROFILE_SOURCES,
    PLANNER_PROVIDERS,
    NOTIFIERS,
)


def available(group: str) -> dict[str, str]:
    """Adapter names registered in a group, mapped to their ``module:attr`` target."""
    return {ep.name: ep.value for ep in entry_points(group=group)}


def load(group: str, name: str) -> object:
    """Import and return the adapter class registered under ``name``."""
    for ep in entry_points(group=group):
        if ep.name == name:
            return ep.load()
    known = ", ".join(sorted(available(group))) or "none"
    raise LookupError(f"no adapter {name!r} in {group} (installed: {known})")
