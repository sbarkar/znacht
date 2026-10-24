from __future__ import annotations

from typing import Protocol, runtime_checkable

from znacht.domain.household import HealthProfile


@runtime_checkable
class HealthProfileSource(Protocol):
    name: str

    async def load(self, household_id: str) -> HealthProfile: ...
