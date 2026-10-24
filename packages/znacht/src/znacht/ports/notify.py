from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import Field

from znacht.domain._base import Frozen


class PlanEvent(Frozen):
    kind: str
    title: str
    message: str
    actions: tuple[str, ...] = ()
    data: dict[str, str] = Field(default_factory=dict)


@runtime_checkable
class Notifier(Protocol):
    name: str

    async def notify(self, event: PlanEvent) -> None: ...
