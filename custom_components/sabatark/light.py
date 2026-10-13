"""Lights: controller outputs used for lighting."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from sabatark import Device

from .entity import SabatarkEntity
from .hub import SabatarkConfigEntry


def is_light(device: Device) -> bool:
    """Return whether an output drives a light."""
    return device.is_output and (device.type in ("light", "outputPwm") or "light" in device.usage)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SabatarkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a light per lighting output."""
    hub = entry.runtime_data
    async_add_entities(
        SabatarkLight(hub, device, "light") for device in hub.devices.values() if is_light(device)
    )


class SabatarkLight(SabatarkEntity, LightEntity):
    """An on/off light output."""

    _attr_name = None
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = frozenset({ColorMode.ONOFF})

    @property
    def is_on(self) -> bool | None:
        value = self.device.status.get("output")
        return value if isinstance(value, bool) else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hub.async_set_output(self.device_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hub.async_set_output(self.device_id, False)
