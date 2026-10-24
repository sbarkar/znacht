from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ZnachtApi, ZnachtApiError
from .const import DEFAULT_SCAN_SECONDS, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ZnachtCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, api: ZnachtApi) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=DEFAULT_SCAN_SECONDS)
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            status = await self.api.status()
            lists = await self.api.lists()
            calendar = await self.api.calendar()
        except ZnachtApiError as exc:
            raise UpdateFailed(str(exc)) from exc
        return {"status": status, "lists": lists, "calendar": calendar}
