from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.hassio import is_hassio
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from . import addon
from .api import ZnachtApi, ZnachtApiError
from .const import CONF_ADDON, CONF_ADDON_SLUG, CONF_TOKEN, CONF_URL, DOMAIN

SCHEMA = vol.Schema(
    {vol.Required(CONF_URL, default="http://znacht.local:8787"): str, vol.Optional(CONF_TOKEN): str}
)

_EMAIL = TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username"))
_SECRET = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
# which form field a failing connection belongs to (GET /api/connections roles)
_FIELD_FOR = {
    "recipes": ("cookidoo_password", "cookidoo_failed"),
    "sink": ("cookidoo_password", "cookidoo_failed"),
    "store": ("migros_password", "migros_failed"),
    "planner": ("anthropic_api_key", "anthropic_failed"),
}


def _accounts_schema(current: dict[str, Any]) -> vol.Schema:
    """Emails are prefilled; secrets are never shown again (empty keeps the stored one)."""
    return vol.Schema(
        {
            vol.Optional(
                "cookidoo_email", description={"suggested_value": current.get("cookidoo_email")}
            ): _EMAIL,
            vol.Optional("cookidoo_password"): _SECRET,
            vol.Optional(
                "migros_email", description={"suggested_value": current.get("migros_email")}
            ): _EMAIL,
            vol.Optional("migros_password"): _SECRET,
            vol.Optional("migros_totp_secret"): _SECRET,
            vol.Optional("anthropic_api_key"): _SECRET,
        }
    )


async def _connection_errors(api: ZnachtApi) -> tuple[dict[str, str], str]:
    """Ask the engine which accounts work; form errors and a sentence of details."""
    try:
        checks: dict[str, dict[str, Any]] = await api.connections()
    except Exception:  # an engine without the endpoint: nothing to report
        return {}, ""
    errors: dict[str, str] = {}
    details: list[str] = []
    for role, check in checks.items():
        if not check.get("ok", True) and role in _FIELD_FOR:
            field, code = _FIELD_FOR[role]
            errors[field] = code
            if check.get("detail") and check["detail"] not in details:
                details.append(str(check["detail"]))
    return errors, " ".join(details)


class ZnachtConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    _discovered: dict[str, Any]
    _addon_name: str

    def __init__(self) -> None:
        self._accounts: dict[str, Any] = {}
        self._engine: addon.AddonEngine | None = None
        self._install_task: asyncio.Task[addon.AddonEngine] | None = None
        self._install_error = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return ZnachtOptionsFlow()

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
        """On Home Assistant OS, offer to run Znacht here; elsewhere, connect to an engine."""
        if is_hassio(self.hass):
            return self.async_show_menu(step_id="user", menu_options=["addon", "manual"])
        return await self.async_step_manual()

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._check(user_input)
            if not errors:
                await self.async_set_unique_id(user_input[CONF_URL])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Znacht", data=user_input)
        return self.async_show_form(step_id="manual", data_schema=SCHEMA, errors=errors)

    # -- run Znacht here: the add-on, installed and set up from this flow (ADR-0013) ------------
    async def async_step_addon(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The accounts. Each can stay empty: that part then runs on sample data."""
        if user_input is not None:
            self._accounts = user_input
            return await self.async_step_install()
        return self.async_show_form(step_id="addon", data_schema=_accounts_schema({}))

    async def async_step_install(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._install_task is None:
            self._install_task = self.hass.async_create_task(
                addon.install_and_start(self.hass, self._accounts)
            )
        if not self._install_task.done():
            return self.async_show_progress(
                step_id="install", progress_action="install", progress_task=self._install_task
            )
        try:
            self._engine = self._install_task.result()
        except Exception as exc:
            self._install_error = str(exc)
            return self.async_show_progress_done(next_step_id="install_failed")
        finally:
            self._install_task = None
        return self.async_show_progress_done(next_step_id="finish")

    async def async_step_install_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_abort(
            reason="addon_failed", description_placeholders={"error": self._install_error}
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Check the accounts; a failing one goes back to the form with the reason."""
        assert self._engine is not None
        engine = self._engine
        api = ZnachtApi(async_get_clientsession(self.hass), engine.url, engine.token)
        errors, details = await _connection_errors(api)
        if errors:
            return self.async_show_form(
                step_id="addon",
                data_schema=_accounts_schema(self._accounts),
                errors=errors,
                description_placeholders={"details": details},
            )
        await self.async_set_unique_id(engine.url, raise_on_progress=False)
        self._abort_if_unique_id_configured(
            updates={CONF_TOKEN: engine.token, CONF_ADDON: True, CONF_ADDON_SLUG: engine.slug}
        )
        return self.async_create_entry(
            title="Znacht",
            data={
                CONF_URL: engine.url,
                CONF_TOKEN: engine.token,
                CONF_ADDON: True,
                CONF_ADDON_SLUG: engine.slug,
            },
        )

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


class ZnachtOptionsFlow(OptionsFlow):
    """Change the accounts of the add-on this integration installed."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        slug = self.config_entry.data.get(CONF_ADDON_SLUG)
        if not slug:
            return self.async_abort(reason="not_addon")
        errors: dict[str, str] = {}
        placeholders = {"details": ""}
        if user_input is not None:
            try:
                await addon.update_accounts(self.hass, slug, user_input)
                await asyncio.sleep(5)  # let the engine come back before asking it
                data = self.config_entry.data
                api = ZnachtApi(
                    async_get_clientsession(self.hass), data[CONF_URL], data[CONF_TOKEN]
                )
                errors, placeholders["details"] = await _connection_errors(api)
            except addon.AddonSetupError as exc:
                errors, placeholders["details"] = {"base": "addon_failed"}, str(exc)
            if not errors:
                return self.async_create_entry(data={})
        current = await addon.addon_options(self.hass, slug)
        return self.async_show_form(
            step_id="init",
            data_schema=_accounts_schema(current),
            errors=errors,
            description_placeholders=placeholders,
        )
