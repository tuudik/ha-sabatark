"""The Sabatark integration for Agatark (EnLife) controllers."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.const import CONF_EMAIL, CONF_HOST, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError, ConfigEntryNotReady

from sabatark import AgatarkClient, AgatarkError, AuthError, SessionState

from .const import CONF_SESSION, CONF_SITE_ID, CONF_TOKEN, DOMAIN, PLATFORMS
from .hub import SabatarkConfigEntry, SabatarkHub

_LOGGER = logging.getLogger(__name__)


def restore_session(data: dict[str, Any]) -> SessionState | None:
    """Return the session stored in config entry data, or None when absent or invalid."""
    stored = data.get(CONF_SESSION)
    if not stored:
        return None
    try:
        return SessionState.from_dict(stored)
    except ValueError:
        _LOGGER.debug("Ignoring an invalid stored session")
        return None


async def async_setup_entry(hass: HomeAssistant, entry: SabatarkConfigEntry) -> bool:
    """Set up a controller site from a config entry."""

    @callback
    def save_session(state: SessionState | None) -> None:
        data = {key: value for key, value in entry.data.items() if key != CONF_SESSION}
        if state is not None:
            data[CONF_SESSION] = state.to_dict()
        hass.config_entries.async_update_entry(entry, data=data)

    @callback
    def connection_changed(connected: bool) -> None:
        hub = getattr(entry, "runtime_data", None)
        if isinstance(hub, SabatarkHub) and hub.client is client:
            hub.async_handle_connection_change(connected)

    client = AgatarkClient(
        entry.data[CONF_HOST],
        email=entry.data[CONF_EMAIL],
        token=entry.data[CONF_TOKEN],
        session_state=restore_session(dict(entry.data)),
        on_session_change=save_session,
        on_connection_change=connection_changed,
    )
    try:
        sites = await client.sites()
        devices = await client.devices()
        rooms = await client.rooms()
    except AuthError as err:
        await client.close()
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from err
    except (AgatarkError, aiohttp.ClientError, TimeoutError) as err:
        await client.close()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err) or type(err).__name__},
        ) from err

    site = next((site for site in sites if site.id == entry.data[CONF_SITE_ID]), None)
    if site is None:
        await client.close()
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="site_not_found")

    hub = SabatarkHub(hass, entry, client, site, devices, rooms)
    entry.runtime_data = hub
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, hub.async_stop))

    hub.async_register_hub_device()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hub.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SabatarkConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_stop()
    return unloaded
