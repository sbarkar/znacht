from __future__ import annotations

from znacht.ports.notify import PlanEvent


class MemoryNotifier:
    name = "memory"

    def __init__(self) -> None:
        self.events: list[PlanEvent] = []

    async def notify(self, event: PlanEvent) -> None:
        self.events.append(event)
