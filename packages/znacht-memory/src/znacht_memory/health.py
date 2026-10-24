from __future__ import annotations

from collections.abc import Mapping

from znacht.domain.household import HealthProfile


class MemoryHealthProfileSource:
    name = "memory"

    def __init__(self, profiles: Mapping[str, HealthProfile] | None = None) -> None:
        self._profiles = dict(profiles or {})

    async def load(self, household_id: str) -> HealthProfile:
        return self._profiles.get(household_id, HealthProfile())
