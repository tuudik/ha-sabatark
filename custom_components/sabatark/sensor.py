"""Sensors: numeric status values such as climate readings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfRatio,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from sabatark import Device

from .const import DOMAIN
from .entity import SabatarkEntity
from .hub import SabatarkConfigEntry, SabatarkHub

KNOWN: dict[str, SensorEntityDescription] = {
    description.key: description
    for description in (
        SensorEntityDescription(
            key="temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="rh",
            device_class=SensorDeviceClass.HUMIDITY,
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="co2",
            device_class=SensorDeviceClass.CO2,
            native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="lux",
            device_class=SensorDeviceClass.ILLUMINANCE,
            native_unit_of_measurement=LIGHT_LUX,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="current",
            device_class=SensorDeviceClass.CURRENT,
            native_unit_of_measurement=UnitOfElectricCurrent.MILLIAMPERE,
            state_class=SensorStateClass.MEASUREMENT,
        ),
    )
}
IGNORED = frozenset(
    {"level", "fadeTime", "dim", "time", "uptime", "address", "baudRate", "format", "serial"}
)
SKIPPED_TYPES = frozenset({"access"})


@dataclass(frozen=True, kw_only=True)
class SabatarkSensorDescription(SensorEntityDescription):
    """Sensor reading one numeric status key."""

    status_key: str


def is_number(value: object) -> bool:
    """Return whether a status value is a number."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def describe(device: Device) -> list[SabatarkSensorDescription]:
    """Return the sensors a device provides, one per numeric status key."""
    if device.type in SKIPPED_TYPES:
        return []
    descriptions: list[SabatarkSensorDescription] = []
    for key, value in device.status.items():
        if key in IGNORED or not is_number(value):
            continue
        known = KNOWN.get(key)
        if known is not None:
            descriptions.append(
                SabatarkSensorDescription(
                    key=key,
                    device_class=known.device_class,
                    native_unit_of_measurement=known.native_unit_of_measurement,
                    state_class=known.state_class,
                    status_key=key,
                )
            )
        else:
            descriptions.append(
                SabatarkSensorDescription(
                    key=key,
                    translation_key="status_value",
                    translation_placeholders={"key": key},
                    state_class=SensorStateClass.MEASUREMENT,
                    entity_registry_enabled_default=False,
                    status_key=key,
                )
            )
    return descriptions


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SabatarkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a sensor per numeric status key."""
    hub = entry.runtime_data
    async_add_entities(
        SabatarkSensor(hub, device, description)
        for device in hub.devices.values()
        for description in describe(device)
    )
    async_add_entities([SabatarkLastPowerLossSensor(hub)])


class SabatarkSensor(SabatarkEntity, SensorEntity):
    """A numeric status key of a controller device."""

    entity_description: SabatarkSensorDescription

    def __init__(
        self, hub: SabatarkHub, device: Device, description: SabatarkSensorDescription
    ) -> None:
        super().__init__(hub, device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        value = self.device.status.get(self.entity_description.status_key)
        return value if is_number(value) else None


class SabatarkLastPowerLossSensor(SensorEntity):
    """When an I/O module of the site last lost power."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "last_power_loss"

    def __init__(self, hub: SabatarkHub) -> None:
        self.hub = hub
        self._attr_unique_id = f"{hub.site_id}_last_power_loss"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, hub.hub_identifier)})

    @property
    def native_value(self) -> datetime | None:
        restore = self.hub.restore
        return restore.last_power_loss if restore is not None else None

    async def async_added_to_hass(self) -> None:
        if self.hub.restore is not None:
            self.async_on_remove(self.hub.restore.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
