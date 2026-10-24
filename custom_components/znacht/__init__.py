"""Znacht: weekly meal planning and grocery splitting, run by a separate engine."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HassJob, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later

from .api import ZnachtApi, ZnachtApiError
from .const import (
    CONF_TOKEN,
    CONF_URL,
    DOMAIN,
    PLATFORMS,
    SERVICE_APPLY,
    SERVICE_OPTIMIZE,
    SERVICE_PANTRY,
    SERVICE_PLAN_WEEK,
    SERVICE_REFRESH,
)
from .coordinator import ZnachtCoordinator

type ZnachtConfigEntry = ConfigEntry[ZnachtCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: ZnachtConfigEntry) -> bool:
    api = ZnachtApi(async_get_clientsession(hass), entry.data[CONF_URL], entry.data.get(CONF_TOKEN))
    coordinator = ZnachtCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass, coordinator)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ZnachtConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _register_services(hass: HomeAssistant, coordinator: ZnachtCoordinator) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_PLAN_WEEK):
        return

    def _friendly(exc: ZnachtApiError) -> HomeAssistantError:
        text = str(exc)
        if "409" in text:
            return HomeAssistantError(
                "Znacht is busy with the previous request; try again in a minute."
            )
        if "401" in text:
            return HomeAssistantError("The Znacht engine rejected the API token.")
        return HomeAssistantError(f"Znacht engine error: {text[:200]}")

    @callback
    def _refresh_now(_now: object) -> None:
        hass.async_create_task(coordinator.async_request_refresh())

    def _refresh_soon(delays: tuple[int, ...] = (30, 90, 180)) -> None:
        """Planning runs in the background on the engine: poll a few times so entities catch up."""
        job = HassJob(_refresh_now, "znacht refresh after planning", cancel_on_shutdown=True)
        for delay in delays:
            async_call_later(hass, delay, job)

    async def plan_week(call: ServiceCall) -> None:
        try:
            await coordinator.api.plan_week(call.data.get("week"))
        except ZnachtApiError as exc:
            raise _friendly(exc) from exc
        await coordinator.async_request_refresh()
        _refresh_soon()

    async def optimize(call: ServiceCall) -> None:
        try:
            await coordinator.api.optimize()
        except ZnachtApiError as exc:
            raise _friendly(exc) from exc
        await coordinator.async_request_refresh()
        _refresh_soon()

    async def apply(call: ServiceCall) -> None:
        try:
            await coordinator.api.apply(call.data.get("run_id"))
        except ZnachtApiError as exc:
            raise _friendly(exc) from exc
        await coordinator.async_request_refresh()

    async def pantry(call: ServiceCall) -> None:
        try:
            await coordinator.api.pantry(dict(call.data["items"]))
        except ZnachtApiError as exc:
            raise _friendly(exc) from exc

    async def refresh(call: ServiceCall) -> None:
        try:
            await coordinator.api.refresh()
        except ZnachtApiError as exc:
            raise _friendly(exc) from exc
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_PLAN_WEEK, plan_week, schema=vol.Schema({vol.Optional("week"): cv.string})
    )
    hass.services.async_register(DOMAIN, SERVICE_OPTIMIZE, optimize)
    hass.services.async_register(
        DOMAIN, SERVICE_APPLY, apply, schema=vol.Schema({vol.Optional("run_id"): cv.positive_int})
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PANTRY, pantry, schema=vol.Schema({vol.Required("items"): dict})
    )
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh)
