from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import ZnachtApi, ZnachtApiError
from .const import CONF_ADDON, CONF_TOKEN, CONF_URL, DOMAIN

SCHEMA = vol.Schema(
    {vol.Required(CONF_URL, default="http://znacht.local:8787"): str, vol.Optional(CONF_TOKEN): str}
)


class ZnachtConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    _discovered: dict[str, Any]
    _addon_name: str

    async def _check(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Reach the engine with the given URL and token; return form errors, empty when fine."""
        api = ZnachtApi(
            async_get_clientsession(self.hass), user_input[CONF_URL], user_input.get(CONF_TOKEN)
        )
        try:
            await api.health()
            await api.status()
        except ZnachtApiError as exc:
            return {"base": "invalid_auth" if "401" in str(exc) else "cannot_connect"}
        except Exception:
            return {"base": "cannot_connect"}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._check(user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_URL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Znacht", data=user_input)
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)

    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> ConfigFlowResult:
        """The Znacht add-on announced itself through the Supervisor (ADR-0012)."""
        url = str(discovery_info.config[CONF_URL])
        token = str(discovery_info.config.get(CONF_TOKEN) or "")
        await self.async_set_unique_id(url)
        # the add-on may have made a new token; an existing entry for it just picks that up
        self._abort_if_unique_id_configured(updates={CONF_TOKEN: token, CONF_ADDON: True})
        self._discovered = {CONF_URL: url, CONF_TOKEN: token, CONF_ADDON: True}
        self._addon_name = discovery_info.name
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._check(self._discovered)
            if not errors:
                return self.async_create_entry(title="Znacht", data=self._discovered)
        return self.async_show_form(
            step_id="hassio_confirm",
            description_placeholders={"addon": self._addon_name},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Move the integration to another engine (the LXC after the workstation, say)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._check(user_input)
            if not errors:
                data = dict(user_input)
                # a new token for the same add-on keeps it the add-on; another URL is another
                # engine, which needs the iframe panel again
                if entry.data.get(CONF_ADDON) and user_input[CONF_URL] == entry.data.get(CONF_URL):
                    data[CONF_ADDON] = True
                return self.async_update_reload_and_abort(
                    entry, unique_id=user_input[CONF_URL], data=data
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=entry.data.get(CONF_URL)): str,
                vol.Optional(CONF_TOKEN, default=entry.data.get(CONF_TOKEN, "")): str,
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)
