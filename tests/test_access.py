"""Tests for access door sensors and detectors that duplicate access inputs."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sabatark import Device

from custom_components.sabatark.const import DOMAIN
from custom_components.sabatark.hub import duplicate_detectors

from .conftest import SITE_ID, FakeController, entity_id

DOOR_INPUT = {"id": 3001, "path": "/inputs/in4", "mode": "input", "target": "/status/open"}


def _device(device_id: int, type_: str, status: dict[str, Any] | None, conf: list) -> dict:
    data: dict[str, Any] = {
        "id": device_id,
        "name": f"Test {type_} {device_id}",
        "type": type_,
        "roomId": 100,
        "siteId": SITE_ID,
        "usage": {type_: [""]},
        "conf": conf,
    }
    if status is not None:
        data["status"] = status
    return data


async def _setup(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_gate_inputs_are_not_door_state(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    controller.devices.append(
        _device(
            1201,
            "access",
            {"online": True, "locked": True, "output2": True, "open1": False, "open2": True},
            [],
        )
    )
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("binary_sensor", DOMAIN, f"{SITE_ID}_1201_door") is None
    assert hass.states.get(entity_id(hass, "binary_sensor", 1010, "door")).state == "off"
    assert entity_id(hass, "button", 1201, "button_locked")


async def test_duplicate_detector_is_skipped(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    controller.devices += [
        _device(1202, "access", {"online": True, "locked": True, "open": False}, [DOOR_INPUT]),
        _device(1203, "securityDetector", None, [{"id": 3001, "path": "/inputs/in4"}]),
        _device(1204, "securityDetector", None, [{"id": 3001, "path": "/inputs/in5"}]),
        _device(1205, "securityDetector", {"online": True, "open": False}, [DOOR_INPUT]),
        _device(1206, "securityDetector", None, []),
    ]
    with caplog.at_level(logging.DEBUG, logger="custom_components.sabatark"):
        await _setup(hass, config_entry)
    hub = config_entry.runtime_data
    assert 1203 not in hub.devices
    assert {1204, 1205, 1206} <= set(hub.devices)
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("binary_sensor", DOMAIN, f"{SITE_ID}_1203_opening") is None
    assert (
        dr.async_get(hass).async_get_device_by_identifier(
            (DOMAIN, f"{SITE_ID}_1203"), config_entry.entry_id
        )
        is None
    )
    for device_id in (1204, 1205, 1206):
        assert entity_id(hass, "binary_sensor", device_id, "opening")
    assert entity_id(hass, "binary_sensor", 1202, "door")
    assert any(
        record.levelno == logging.DEBUG and "1203" in record.getMessage()
        for record in caplog.records
    )


def test_duplicate_detectors_need_every_conf_matched() -> None:
    access = Device.from_dict(_device(1, "access", {"open": False}, [DOOR_INPUT]))
    output_conf = {"id": 3002, "path": "/outputs/out1", "mode": "output"}
    other_access = Device.from_dict(_device(2, "access", {}, [output_conf]))
    detectors = [
        Device.from_dict(_device(10, "securityDetector", None, [DOOR_INPUT])),
        Device.from_dict(_device(11, "securityDetector", {}, [DOOR_INPUT, output_conf])),
        Device.from_dict(_device(12, "securityDetector", None, [output_conf])),
        Device.from_dict(_device(13, "input", None, [DOOR_INPUT])),
    ]
    assert duplicate_detectors([access, other_access, *detectors]) == {10}
