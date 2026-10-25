"""Install, configure and start the Znacht add-on through the Supervisor (ADR-0013).

Only used on Home Assistant OS and Supervised installs; everything here goes through Home
Assistant's own add-on manager, the way Z-Wave JS and Matter set up theirs.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant

ADDON_REPOSITORY = "https://github.com/sbarkar/znacht"
ADDON_NAME = "Znacht"
_LOGGER = logging.getLogger(__name__)

# the account fields the integration's form asks for, as add-on option names
ACCOUNT_FIELDS = (
    "cookidoo_email",
    "cookidoo_password",
    "migros_email",
    "migros_password",
    "migros_totp_secret",
    "anthropic_api_key",
    "ha_notify",  # the phone, not an account, but asked on the same form
)
SECRET_FIELDS = ("cookidoo_password", "migros_password", "migros_totp_secret", "anthropic_api_key")


class AddonSetupError(Exception):
    """The add-on could not be installed, configured or reached; the message says why."""


@dataclass
class AddonEngine:
    slug: str
    url: str
    token: str


def accounts_to_options(current: dict[str, Any], accounts: dict[str, Any]) -> dict[str, Any]:
    """Merge the form into the add-on's options. An empty secret keeps the stored one; an empty
    email switches that service to the sample adapters."""
    options = dict(current)
    for key in ACCOUNT_FIELDS:
        value = str(accounts.get(key) or "").strip()
        if key in SECRET_FIELDS and not value and options.get(key):
            continue
        options[key] = value
    cookidoo = bool(options.get("cookidoo_email"))
    options["recipe_source"] = options["sink"] = "cookidoo" if cookidoo else "memory"
    options["store"] = "migros" if options.get("migros_email") else "memory"
    options["planner"] = "anthropic" if options.get("anthropic_api_key") else "rule_based"
    return options


async def find_addon_slug(hass: HomeAssistant) -> str:
    """The add-on's slug, adding the Znacht repository to the add-on store when it is missing."""
    from aiohasupervisor.models import StoreAddRepository
    from homeassistant.components.hassio import get_supervisor_client

    client = get_supervisor_client(hass)
    for attempt in range(2):
        for repo in await client.store.repositories_list():
            if repo.source.rstrip("/").removesuffix(".git") == ADDON_REPOSITORY:
                return f"{repo.slug}_znacht"
        if attempt == 0:
            _LOGGER.info("Adding the Znacht add-on repository to the add-on store")
            await client.store.add_repository(StoreAddRepository(repository=ADDON_REPOSITORY))
    raise AddonSetupError("the Znacht add-on repository could not be added to the add-on store")


def _manager(hass: HomeAssistant, slug: str) -> Any:
    from homeassistant.components.hassio import AddonManager

    return AddonManager(hass, _LOGGER, ADDON_NAME, slug)


async def addon_options(hass: HomeAssistant, slug: str) -> dict[str, Any]:
    info = await _manager(hass, slug).async_get_addon_info()
    return dict(info.options or {})


async def install_and_start(hass: HomeAssistant, accounts: dict[str, Any]) -> AddonEngine:
    """Install (first time: the Supervisor builds the image, a few minutes), set the accounts,
    (re)start, and wait until the add-on announces itself and answers."""
    from homeassistant.components.hassio import AddonError, AddonState

    try:
        slug = await find_addon_slug(hass)
        manager = _manager(hass, slug)
        info = await manager.async_get_addon_info()
        if info.state == AddonState.NOT_INSTALLED:
            await manager.async_install_addon()
            info = await manager.async_get_addon_info()
            await _show_in_sidebar(hass, slug)
        await manager.async_set_addon_options(accounts_to_options(dict(info.options), accounts))
        if info.state == AddonState.RUNNING:
            await manager.async_restart_addon()
        else:
            await manager.async_start_addon()
        return await _wait_for_engine(hass, manager, slug)
    except AddonError as exc:
        raise AddonSetupError(str(exc)) from exc


async def _show_in_sidebar(hass: HomeAssistant, slug: str) -> None:
    """An add-on installed through the API is not in the sidebar; the app lives there. The
    watchdog restarts the engine if it ever stops."""
    from aiohasupervisor.models import AddonsOptions
    from homeassistant.components.hassio import get_supervisor_client

    await get_supervisor_client(hass).addons.set_addon_options(
        slug, AddonsOptions(ingress_panel=True, watchdog=True)
    )


async def update_accounts(hass: HomeAssistant, slug: str, accounts: dict[str, Any]) -> None:
    """Change the accounts later (the integration's Configure button) and restart the add-on."""
    from homeassistant.components.hassio import AddonError

    manager = _manager(hass, slug)
    try:
        current = await addon_options(hass, slug)
        await manager.async_set_addon_options(accounts_to_options(current, accounts))
        await manager.async_restart_addon()
    except AddonError as exc:
        raise AddonSetupError(str(exc)) from exc


WAIT_SECONDS = 180.0  # the engine loads its recipe cache and signs in before it answers


async def _wait_for_engine(hass: HomeAssistant, manager: Any, slug: str) -> AddonEngine:
    from homeassistant.components.hassio import AddonError
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .api import ZnachtApi

    deadline = asyncio.get_running_loop().time() + WAIT_SECONDS
    last = "the add-on did not start"
    while asyncio.get_running_loop().time() < deadline:
        try:
            config = await manager.async_get_addon_discovery_info()
            url, token = str(config["url"]), str(config.get("token") or "")
            await ZnachtApi(async_get_clientsession(hass), url, token).health()
            return AddonEngine(slug=slug, url=url, token=token)
        except (AddonError, KeyError) as exc:
            last = f"waiting for the add-on to announce itself ({exc})"
        except Exception as exc:  # the engine is still starting
            last = f"the engine did not answer yet ({exc})"
        await asyncio.sleep(3)
    raise AddonSetupError(last)
