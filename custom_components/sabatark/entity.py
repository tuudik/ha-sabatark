"""Base entity for controller devices."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity

from sabatark import Device

from .controls import DEFAULT_ONOFF, status_key
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


class SabatarkOnOffEntity(SabatarkEntity):
    """Entity switched through the device's declared on/off status path."""

    def __init__(self, hub: SabatarkHub, device: Device, key: str) -> None:
        super().__init__(hub, device, key)
        self.controls = hub.controls(device.id)
        self._onoff_key = status_key(self.controls.onoff or DEFAULT_ONOFF) or "output"

    @property
    def is_on(self) -> bool | None:
        value = self.device.status.get(self._onoff_key)
        return value if isinstance(value, bool) else None

    async def _async_write_onoff(self, on: bool, extra: Mapping[str, Any] | None = None) -> None:
        if self._onoff_key == "output" and not extra:
            await self.hub.async_set_output(self.device_id, on)
        else:
            await self.hub.async_patch_status(
                self.device_id, {self._onoff_key: on, **(extra or {})}
            )
