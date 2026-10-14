"""Pulse buttons for access outputs."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from sabatark import Device

from .entity import SabatarkEntity
from .hub import SabatarkConfigEntry, SabatarkHub
from .options_flow import access_options, status_key


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SabatarkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a pulse button for each configured access output."""
    hub = entry.runtime_data
    async_add_entities(
        SabatarkButton(hub, device, path, index)
        for device in hub.devices.values()
        if device.type == "access"
        and (options := access_options(entry, device.id))["model"] == "buttons"
        for index, path in enumerate(options["paths"], start=1)
    )


class SabatarkButton(SabatarkEntity, ButtonEntity):
    """A single access output pulse."""

    def __init__(self, hub: SabatarkHub, device: Device, path: str, index: int) -> None:
        self._output_key = status_key(path)
        super().__init__(hub, device, f"button_{self._output_key}")
        if index == 1:
            self._attr_translation_key = "impulse"
        else:
            self._attr_translation_key = "impulse_number"
            self._attr_translation_placeholders = {"number": str(index)}

    async def async_press(self) -> None:
        """Pulse the configured output."""
        await self.hub.async_patch_status(self.device_id, {self._output_key: False})
