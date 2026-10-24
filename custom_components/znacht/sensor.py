from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ZnachtConfigEntry
from .const import DOMAIN
from .coordinator import ZnachtCoordinator


@dataclass(frozen=True, kw_only=True)
class ZnachtSensorDescription(SensorEntityDescription):
    value: Callable[[dict[str, Any]], Any]


SENSORS: tuple[ZnachtSensorDescription, ...] = (
    ZnachtSensorDescription(
        key="plan_status", translation_key="plan_status", value=lambda s: s.get("plan_status")
    ),
    ZnachtSensorDescription(
        key="basket_total",
        translation_key="basket_total",
        native_unit_of_measurement="CHF",
        value=lambda s: s.get("basket_total"),
    ),
    ZnachtSensorDescription(
        key="minimum_order",
        translation_key="minimum_order",
        value=lambda s: (
            ("met" if s.get("meets_minimum") else f"short {s.get('shortfall')}")
            if s.get("run_id")
            else None
        ),
    ),
    ZnachtSensorDescription(
        key="next_delivery", translation_key="next_delivery", value=lambda s: s.get("next_delivery")
    ),
    ZnachtSensorDescription(
        key="todays_dinner", translation_key="todays_dinner", value=lambda s: s.get("todays_dinner")
    ),
    ZnachtSensorDescription(
        key="savings",
        translation_key="savings",
        native_unit_of_measurement="CHF",
        value=lambda s: s.get("savings"),
    ),
    ZnachtSensorDescription(
        key="lifetime_savings",
        translation_key="lifetime_savings",
        native_unit_of_measurement="CHF",
        value=lambda s: s.get("lifetime_savings"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ZnachtConfigEntry, add: AddEntitiesCallback
) -> None:
    add(ZnachtSensor(entry.runtime_data, entry.entry_id, d) for d in SENSORS)


class ZnachtSensor(CoordinatorEntity[ZnachtCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: ZnachtSensorDescription

    def __init__(
        self, coordinator: ZnachtCoordinator, entry_id: str, description: ZnachtSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Znacht",
            "manufacturer": "Znacht",
        }

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data.get("status", {}))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self.coordinator.data.get("status", {})
        if self.entity_description.key == "plan_status":
            return {
                k: status.get(k)
                for k in (
                    "run_id",
                    "week",
                    "theme",
                    "brief_url",
                    "switches",
                    "flags",
                    "violations",
                    "busy",
                )
            }
        return {}
