"""Base entity for controller devices."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity

from sabatark import Device

from .hub import SabatarkHub


class SabatarkEntity(Entity):
    """Entity bound to one key of a controller device, updated by the hub's event stream."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: SabatarkHub, device: Device, key: str) -> None:
        self.hub = hub
        self.device_id = device.id
        self.key = key
        self._attr_unique_id = hub.unique_id(device.id, key)
        self._attr_device_info = hub.device_info(device)

    @property
    def device(self) -> Device:
        """Return the current state of the controller device."""
        return self.hub.devices[self.device_id]

    @property
    def available(self) -> bool:
        return self.hub.is_available(self.device_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.async_subscribe_device(self.device_id, self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
