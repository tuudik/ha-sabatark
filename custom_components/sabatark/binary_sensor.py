"""Binary sensors: motion, openings, safety detectors and raw switch inputs."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from sabatark import Device

from .entity import SabatarkEntity
from .hub import SabatarkConfigEntry, SabatarkHub

SAFETY_CLASSES: dict[str, BinarySensorDeviceClass] = {
    "fire": BinarySensorDeviceClass.SMOKE,
    "smoke": BinarySensorDeviceClass.SMOKE,
    "heat": BinarySensorDeviceClass.HEAT,
    "co": BinarySensorDeviceClass.CO,
    "gas": BinarySensorDeviceClass.GAS,
    "water": BinarySensorDeviceClass.MOISTURE,
    "leak": BinarySensorDeviceClass.MOISTURE,
    "flood": BinarySensorDeviceClass.MOISTURE,
}
OPENING_CLASSES: dict[str, BinarySensorDeviceClass] = {
    "door": BinarySensorDeviceClass.DOOR,
    "window": BinarySensorDeviceClass.WINDOW,
    "garage": BinarySensorDeviceClass.GARAGE_DOOR,
}


@dataclass(frozen=True, kw_only=True)
class SabatarkBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor reading one boolean status key."""

    status_key: str


def describe(device: Device) -> list[SabatarkBinarySensorDescription]:
    """Return the binary sensors a device provides."""
    status = device.status
    if device.is_motion:
        return [
            SabatarkBinarySensorDescription(
                key="motion",
                name=None,
                device_class=BinarySensorDeviceClass.MOTION,
                status_key="active",
            )
        ]
    if device.type == "securityDetector":
        usage = device.usage.get("securityDetector", [])
        device_class = next(
            (OPENING_CLASSES[item] for item in usage if item in OPENING_CLASSES),
            BinarySensorDeviceClass.OPENING,
        )
        return [
            SabatarkBinarySensorDescription(
                key="opening",
                name=None,
                device_class=device_class,
                status_key="open" if "open" in status or "active" not in status else "active",
            )
        ]
    if device.type == "securityDetector24" and "active" in status:
        usage = device.usage.get("securityDetector24", [])
        device_class = next(
            (SAFETY_CLASSES[item] for item in usage if item in SAFETY_CLASSES),
            BinarySensorDeviceClass.SAFETY,
        )
        return [
            SabatarkBinarySensorDescription(
                key="safety", name=None, device_class=device_class, status_key="active"
            )
        ]
    if device.type == "input" and "active" in status:
        return [SabatarkBinarySensorDescription(key="active", name=None, status_key="active")]
    if device.is_switch and "input" in status:
        return [
            SabatarkBinarySensorDescription(
                key="input",
                translation_key="input",
                entity_registry_enabled_default=False,
                status_key="input",
            )
        ]
    return []


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SabatarkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add binary sensors for detectors and switch inputs."""
    hub = entry.runtime_data
    async_add_entities(
        SabatarkBinarySensor(hub, device, description)
        for device in hub.devices.values()
        for description in describe(device)
    )


class SabatarkBinarySensor(SabatarkEntity, BinarySensorEntity):
    """A boolean status key of a controller device."""

    entity_description: SabatarkBinarySensorDescription

    def __init__(
        self, hub: SabatarkHub, device: Device, description: SabatarkBinarySensorDescription
    ) -> None:
        super().__init__(hub, device, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        value = self.device.status.get(self.entity_description.status_key)
        return value if isinstance(value, bool) else None
