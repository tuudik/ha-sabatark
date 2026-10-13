"""Access devices modelled as pulse-operated garage covers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import CoverDeviceClass, CoverEntity, CoverEntityFeature
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
    """Add access devices configured as garage covers."""
    hub = entry.runtime_data
    async_add_entities(
        SabatarkCover(hub, device, options)
        for device in hub.devices.values()
        if device.type == "access"
        and (options := access_options(entry, device.id))["model"] == "cover"
    )


class SabatarkCover(SabatarkEntity, CoverEntity):
    """A pulsed garage cover with a separate binary state source."""

    _attr_name = None
    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

    def __init__(self, hub: SabatarkHub, device: Device, options: dict[str, Any]) -> None:
        super().__init__(hub, device, "cover")
        self._output_key = status_key(options["paths"][0])
        self._state_device = int(options["state_device"])
        self._state_key = status_key(options["state_path"])

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hub.async_subscribe_device(self._state_device, self._handle_update)
        )

    @property
    def available(self) -> bool:
        return super().available and self.hub.is_available(self._state_device)

    @property
    def is_closed(self) -> bool | None:
        device = self.hub.devices.get(self._state_device)
        value = device.status.get(self._state_key) if device else None
        return not value if isinstance(value, bool) else None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Pulse the configured output."""
        await self.hub.async_patch_status(self.device_id, {self._output_key: False})

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Pulse the configured output."""
        await self.hub.async_patch_status(self.device_id, {self._output_key: False})

    async def async_toggle(self, **kwargs: Any) -> None:
        """Pulse the configured output."""
        await self.hub.async_patch_status(self.device_id, {self._output_key: False})
