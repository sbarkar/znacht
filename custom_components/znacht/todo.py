from __future__ import annotations

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ZnachtConfigEntry
from .const import DOMAIN
from .coordinator import ZnachtCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ZnachtConfigEntry, add: AddEntitiesCallback
) -> None:
    add(
        [
            ZnachtTodo(entry.runtime_data, entry.entry_id, "online"),
            ZnachtTodo(entry.runtime_data, entry.entry_id, "in_store"),
        ]
    )


class ZnachtTodo(CoordinatorEntity[ZnachtCoordinator], TodoListEntity):
    _attr_has_entity_name = True
    _attr_supported_features = (
        TodoListEntityFeature.UPDATE_TODO_ITEM | TodoListEntityFeature.CREATE_TODO_ITEM
    )

    def __init__(self, coordinator: ZnachtCoordinator, entry_id: str, kind: str) -> None:
        super().__init__(coordinator)
        self._kind = kind
        self._attr_unique_id = f"{entry_id}_{kind}_list"
        self._attr_translation_key = f"{kind}_list"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Znacht",
            "manufacturer": "Znacht",
        }

    @property
    def todo_items(self) -> list[TodoItem]:
        items = self.coordinator.data.get("lists", {}).get(self._kind, [])
        return [
            TodoItem(
                uid=i["uid"],
                summary=i["summary"],
                description=i.get("description"),
                status=TodoItemStatus.COMPLETED if i.get("done") else TodoItemStatus.NEEDS_ACTION,
            )
            for i in items
        ]

    async def async_update_todo_item(self, item: TodoItem) -> None:
        if item.uid:
            await self.coordinator.api.todo_done(
                self._kind, item.uid, item.status == TodoItemStatus.COMPLETED
            )
            await self.coordinator.async_request_refresh()

    async def async_create_todo_item(self, item: TodoItem) -> None:
        if item.summary:
            await self.coordinator.api.todo_add(self._kind, item.summary)
            await self.coordinator.async_request_refresh()
