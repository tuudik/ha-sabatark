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
        SabatarkButton(hub, device, path)
        for device in hub.devices.values()
        if device.type == "access"
        and (options := access_options(entry, device.id))["model"] == "buttons"
        for path in options["paths"]
    )


class SabatarkButton(SabatarkEntity, ButtonEntity):
    """A single access output pulse."""

    def __init__(self, hub: SabatarkHub, device: Device, path: str) -> None:
        self._output_key = status_key(path)
        super().__init__(hub, device, f"button_{self._output_key}")
        self._attr_translation_key = {
            "locked": "open",
            "output2": "open_secondary",
        }.get(self._output_key, "open_output")
        self._attr_translation_placeholders = {"path": path}

    async def async_press(self) -> None:
        """Pulse the configured output."""
        await self.hub.async_patch_status(self.device_id, {self._output_key: False})
