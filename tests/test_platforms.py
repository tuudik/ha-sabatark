"""Tests for the light, switch, binary_sensor and sensor platforms."""

from __future__ import annotations

import pytest
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.light import ColorMode
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_OFF,
    STATE_ON,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sabatark import AgatarkError, parse_event

from .conftest import SITE_ID, FakeController, entity_id


def _entity_ids(hass: HomeAssistant, platform: Platform) -> set[str]:
    return {
        entry.entity_id
        for entry in er.async_get(hass).entities.values()
        if entry.domain == platform and entry.platform == "sabatark"
    }


async def test_lights(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    assert _entity_ids(hass, Platform.LIGHT) == {
        entity_id(hass, "light", 1001, "light"),
        entity_id(hass, "light", 1002, "light"),
        entity_id(hass, "light", 1003, "light"),
        entity_id(hass, "light", 1012, "light"),
    }
    state = hass.states.get(entity_id(hass, "light", 1002, "light"))
    assert state.state == STATE_ON
    assert state.attributes["supported_color_modes"] == [ColorMode.ONOFF]


async def test_light_turn_on_and_off(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    await hass.services.async_call(
        "light",
        "turn_on",
        {ATTR_ENTITY_ID: entity_id(hass, "light", 1001, "light")},
        blocking=True,
    )
    await hass.services.async_call(
        "light",
        "turn_off",
        {ATTR_ENTITY_ID: entity_id(hass, "light", 1002, "light")},
        blocking=True,
    )
    assert controller.writes == [("output", 1001, True), ("output", 1002, False)]
    assert hass.states.get(entity_id(hass, "light", 1001, "light")).state == STATE_OFF


async def test_switch(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    assert _entity_ids(hass, Platform.SWITCH) == {entity_id(hass, "switch", 1004, "switch")}
    assert hass.states.get(entity_id(hass, "switch", 1004, "switch")).state == STATE_OFF
    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: entity_id(hass, "switch", 1004, "switch")},
        blocking=True,
    )
    assert controller.writes == [("output", 1004, True)]
    await controller.push(parse_event({"id": 1004, "status": {"output": True}}))
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "switch", 1004, "switch")).state == STATE_ON


async def test_write_error_raises(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    controller.write_error = AgatarkError("HTTP 403", status=403)
    with pytest.raises(HomeAssistantError, match="HTTP 403"):
        await hass.services.async_call(
            "switch",
            "turn_off",
            {ATTR_ENTITY_ID: entity_id(hass, "switch", 1004, "switch")},
            blocking=True,
        )


async def test_patch_status(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    await loaded_entry.runtime_data.async_patch_status(1010, {"locked": False})
    assert controller.writes == [("devices", 1010, {"status": {"locked": False}})]


async def test_binary_sensors(
    hass: HomeAssistant,
    controller: FakeController,
    enable_all_entities: None,
    loaded_entry: MockConfigEntry,
) -> None:
    assert _entity_ids(hass, Platform.BINARY_SENSOR) == {
        entity_id(hass, "binary_sensor", 1005, "input"),
        entity_id(hass, "binary_sensor", 1006, "motion"),
        entity_id(hass, "binary_sensor", 1007, "opening"),
        entity_id(hass, "binary_sensor", 1008, "safety"),
        entity_id(hass, "binary_sensor", 1013, "active"),
    }
    classes = {
        entity_id(hass, "binary_sensor", 1006, "motion"): BinarySensorDeviceClass.MOTION,
        entity_id(hass, "binary_sensor", 1007, "opening"): BinarySensorDeviceClass.DOOR,
        entity_id(hass, "binary_sensor", 1008, "safety"): BinarySensorDeviceClass.SMOKE,
    }
    for target, device_class in classes.items():
        state = hass.states.get(target)
        assert state.state == STATE_OFF
        assert state.attributes[ATTR_DEVICE_CLASS] == device_class

    await controller.push(
        parse_event({"id": 1006, "status": {"active": True}}),
        parse_event({"id": 1007, "status": {"open": True}}),
        parse_event({"id": 1005, "status": {"input": True}}),
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "binary_sensor", 1006, "motion")).state == STATE_ON
    assert hass.states.get(entity_id(hass, "binary_sensor", 1007, "opening")).state == STATE_ON
    assert hass.states.get(entity_id(hass, "binary_sensor", 1005, "input")).state == STATE_ON


async def test_raw_input_disabled_by_default(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    entry = er.async_get(hass).async_get(entity_id(hass, "binary_sensor", 1005, "input"))
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(entity_id(hass, "binary_sensor", 1005, "input")) is None


async def test_sensors(
    hass: HomeAssistant,
    controller: FakeController,
    enable_all_entities: None,
    loaded_entry: MockConfigEntry,
) -> None:
    expected = {
        entity_id(hass, "sensor", 1009, "temperature"): (
            "21.5",
            SensorDeviceClass.TEMPERATURE,
            "°C",
        ),
        entity_id(hass, "sensor", 1009, "rh"): ("40.0", SensorDeviceClass.HUMIDITY, "%"),
        entity_id(hass, "sensor", 1009, "co2"): ("600", SensorDeviceClass.CO2, "ppm"),
        entity_id(hass, "sensor", 1009, "lux"): ("120", SensorDeviceClass.ILLUMINANCE, "lx"),
    }
    for target, (value, device_class, unit) in expected.items():
        state = hass.states.get(target)
        assert state is not None, target
        assert state.state == value
        assert state.attributes[ATTR_DEVICE_CLASS] == device_class
        assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == unit

    generic = hass.states.get(entity_id(hass, "sensor", 1009, "ventilationNeed"))
    assert generic is not None
    assert generic.state == "3"
    assert ATTR_DEVICE_CLASS not in generic.attributes
    assert not any(
        entry.unique_id.startswith(f"{SITE_ID}_1002_")
        for entry in er.async_get(hass).entities.values()
        if entry.domain == "sensor"
    )

    await controller.push(parse_event({"id": 1009, "status": {"temperature": 22.25}}))
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "sensor", 1009, "temperature")).state == "22.25"


async def test_unknown_sensor_disabled_by_default(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    generic = registry.async_get(entity_id(hass, "sensor", 1009, "ventilationNeed"))
    assert generic.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(entity_id(hass, "sensor", 1009, "temperature")) is not None
