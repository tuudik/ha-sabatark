"""Switches: controller outputs that are not lights."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import SabatarkEntity
from .hub import SabatarkConfigEntry
from .light import is_light


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SabatarkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a switch per non-lighting output."""
    hub = entry.runtime_data
    async_add_entities(
        SabatarkSwitch(hub, device, "switch")
        for device in hub.devices.values()
        if device.is_output and not is_light(device)
    )


class SabatarkSwitch(SabatarkEntity, SwitchEntity):
    """A relay output."""

    _attr_name = None

    @property
    def is_on(self) -> bool | None:
        value = self.device.status.get("output")
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hub.async_set_output(self.device_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hub.async_set_output(self.device_id, False)
