from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ZnachtConfigEntry
from .const import DOMAIN
from .coordinator import ZnachtCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ZnachtConfigEntry, add: AddEntitiesCallback
) -> None:
    add([ZnachtCalendar(entry.runtime_data, entry.entry_id)])


class ZnachtCalendar(CoordinatorEntity[ZnachtCoordinator], CalendarEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "meal_plan"

    def __init__(self, coordinator: ZnachtCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_meal_plan"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Znacht",
            "manufacturer": "Znacht",
        }

    def _events(self) -> list[CalendarEvent]:
        out: list[CalendarEvent] = []
        for m in self.coordinator.data.get("calendar", []):
            day = date.fromisoformat(m["date"])
            out.append(
                CalendarEvent(
                    start=day,
                    end=day + timedelta(days=1),
                    summary=m["summary"],
                    description=m.get("note") or m.get("recipe_id"),
                    location=m.get("url"),
                    uid=f"{m['date']}-{m['recipe_id']}",
                )
            )
        return out

    @property
    def event(self) -> CalendarEvent | None:
        today = date.today()
        upcoming = [e for e in self._events() if isinstance(e.start, date) and e.start >= today]
        return min(upcoming, key=lambda e: e.start) if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [e for e in self._events() if start_date.date() <= e.start < end_date.date()]
