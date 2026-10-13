"""Lights: controller outputs used for lighting."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from sabatark import Device

from .controls import brightness_to_level, level_to_brightness, status_key
from .entity import SabatarkOnOffEntity
from .hub import SabatarkConfigEntry, SabatarkHub


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


class SabatarkLight(SabatarkOnOffEntity, LightEntity):
    """A light output, dimmable when the device declares a level slider."""

    _attr_name = None

    def __init__(self, hub: SabatarkHub, device: Device, key: str) -> None:
        super().__init__(hub, device, key)
        level = self.controls.level
        self._target_key = status_key(level.path) if level else None
        mode = ColorMode.BRIGHTNESS if self._target_key else ColorMode.ONOFF
        self._attr_color_mode = mode
        self._attr_supported_color_modes = frozenset({mode})

    @property
    def brightness(self) -> int | None:
        level = self.controls.level
        if level is None or self._target_key is None:
            return None
        status = self.device.status
        value = status["level"] if "level" in status else status.get(self._target_key)
        return level_to_brightness(level, value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        level = self.controls.level
        if ATTR_BRIGHTNESS in kwargs and level is not None and self._target_key is not None:
            value = brightness_to_level(level, kwargs[ATTR_BRIGHTNESS])
            await self._async_write_onoff(True, {self._target_key: value})
        else:
            await self._async_write_onoff(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_write_onoff(False)
