"""Redacted controller diagnostics."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .hub import SabatarkConfigEntry

TO_REDACT = {
    "host",
    "hostname",
    "base_url",
    "email",
    "token",
    "authorization",
    "Authorization",
    "session",
    "user_id",
    "userId",
    "user",
    "password",
    "name",
    "title",
    "unique_id",
    "uuid",
    "serial",
    "mac",
    "ip",
    "device_name",
    "room_name",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SabatarkConfigEntry
) -> dict[str, Any]:
    """Return redacted entry data and current device status."""
    hub = getattr(entry, "runtime_data", None)
    data = {
        "title": entry.title,
        "unique_id": entry.unique_id,
        "data": dict(entry.data),
        "options": dict(entry.options),
    }
    if hub is not None:
        data["hub"] = {
            "connected": hub.connected,
            "site": {"id": hub.site_id, "name": hub.site.name},
            "device_count": len(hub.devices),
            "room_count": len(hub.rooms),
            "devices": [
                {
                    "id": device.id,
                    "name": device.name,
                    "type": device.type,
                    "usage": device.usage,
                    "status": device.status,
                }
                for device in hub.devices.values()
            ],
            "rooms": [{"id": room.id, "name": room.name} for room in hub.rooms.values()],
            "restore": hub.restore.diagnostics() if hub.restore is not None else None,
        }
    return async_redact_data(data, TO_REDACT)
