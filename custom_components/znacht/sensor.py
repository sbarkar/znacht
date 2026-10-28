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
    value: Callable[[dict[str, Any]], Any]  # gets the engine's /api/status document
    attributes: Callable[[dict[str, Any]], dict[str, Any]] | None = None  # gets all data


def _unplanned(data: dict[str, Any]) -> int | None:
    """Days in the timeline horizon with nothing in My Week: empty or only proposed."""
    tl = data.get("timeline") or {}
    if "unplanned_dates" not in tl:
        return None
    return len(tl["unplanned_dates"])


def _unplanned_attributes(data: dict[str, Any]) -> dict[str, Any]:
    tl = data.get("timeline") or {}
    return {
        "dates": list(tl.get("unplanned_dates", [])),
        "empty_dates": list(tl.get("empty_dates", [])),
        "proposed_dates": list(tl.get("proposed_dates", [])),
        "horizon_days": tl.get("horizon"),
        "from": tl.get("from"),
        "weeks": [
            {
                "week": w.get("week"),
                "label": w.get("label"),
                "summary": w.get("summary"),
                "awaiting_run_id": w.get("awaiting_run_id"),
            }
            for w in tl.get("weeks", [])
        ],
    }


def _findings_attributes(data: dict[str, Any]) -> dict[str, Any]:
    status = data.get("status", {})
    return {"findings": list(status.get("findings", [])), "run_id": status.get("run_id")}


SENSORS: tuple[ZnachtSensorDescription, ...] = (
    ZnachtSensorDescription(
        key="plan_status", translation_key="plan_status", value=lambda s: s.get("plan_status")
    ),
    ZnachtSensorDescription(
        # reconciliation findings neither fixed nor overridden (ADR-0016); Approve waits on 0
        key="open_findings",
        translation_key="open_findings",
        icon="mdi:scale-unbalanced",
        value=lambda s: s.get("open_findings"),
        attributes=_findings_attributes,
    ),
    ZnachtSensorDescription(
        key="unplanned_days",
        translation_key="unplanned_days",
        native_unit_of_measurement="days",
        value=lambda s: None,
        attributes=_unplanned_attributes,
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
        if self.entity_description.key == "unplanned_days":
            return _unplanned(self.coordinator.data)
        return self.entity_description.value(self.coordinator.data.get("status", {}))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.entity_description.attributes is not None:
            return self.entity_description.attributes(self.coordinator.data)
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
