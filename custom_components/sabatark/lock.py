"""Access devices modelled as locks."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from sabatark import Device

from .entity import SabatarkEntity
from .hub import SabatarkConfigEntry, SabatarkHub
from .options_flow import access_options


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SabatarkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add access devices configured as locks."""
    hub = entry.runtime_data
    async_add_entities(
        SabatarkLock(hub, device)
        for device in hub.devices.values()
        if device.type == "access" and access_options(entry, device.id)["model"] == "lock"
    )


class SabatarkLock(SabatarkEntity, LockEntity):
    """An access controller's locked status."""

    _attr_name = None

    def __init__(self, hub: SabatarkHub, device: Device) -> None:
        super().__init__(hub, device, "lock")

    @property
    def is_locked(self) -> bool | None:
        value = self.device.status.get("locked")
        return value if isinstance(value, bool) else None

    async def async_lock(self, **kwargs: Any) -> None:
        """Write the locked status."""
        await self.hub.async_patch_status(self.device_id, {"locked": True})

    async def async_unlock(self, **kwargs: Any) -> None:
        """Release the lock until the controller relocks it."""
        await self.hub.async_patch_status(self.device_id, {"locked": False})
