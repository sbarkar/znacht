from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ZnachtApi, ZnachtApiError
from .const import CONF_TOKEN, CONF_URL, DOMAIN

SCHEMA = vol.Schema(
    {vol.Required(CONF_URL, default="http://znacht.local:8787"): str, vol.Optional(CONF_TOKEN): str}
)


class ZnachtConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api = ZnachtApi(
                async_get_clientsession(self.hass), user_input[CONF_URL], user_input.get(CONF_TOKEN)
            )
            try:
                await api.health()
                await api.status()
            except ZnachtApiError as exc:
                errors["base"] = "invalid_auth" if "401" in str(exc) else "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_URL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Znacht", data=user_input)
        return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)
