"""Tests for wall-switch gesture events."""

from __future__ import annotations

import logging

import pytest
from homeassistant.components.event import ATTR_MULTI_PRESS_COUNT, ButtonEventType, EventDeviceClass
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sabatark import parse_event

from .conftest import FakeController, entity_id


@pytest.mark.parametrize(
    ("gesture", "event_type", "count"),
    [
        ("singleClick", ButtonEventType.PRESS_END, None),
        ("longPush", ButtonEventType.LONG_PRESS_END, None),
        ("doubleClick", ButtonEventType.MULTI_PRESS_END, 2),
    ],
)
async def test_gesture(
    hass: HomeAssistant,
    controller: FakeController,
    loaded_entry: MockConfigEntry,
    gesture: str,
    event_type: ButtonEventType,
    count: int | None,
) -> None:
    target = entity_id(hass, "event", 1005, "event")
    assert hass.states.get(target).attributes["device_class"] == EventDeviceClass.BUTTON
    await controller.push(
        parse_event({"op": "log", "id": 1005, "time": 1000, "key": f"{gesture}:/status/input"})
    )
    await hass.async_block_till_done()
    state = hass.states.get(target)
    assert state.state != "unknown"
    assert state.attributes["event_type"] == event_type
    assert state.attributes.get(ATTR_MULTI_PRESS_COUNT) == count
    assert controller.writes == []


async def test_ignored_logs_and_attribute_reset(
    hass: HomeAssistant,
    controller: FakeController,
    loaded_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="custom_components.sabatark.event")
    target = entity_id(hass, "event", 1005, "event")
    before = hass.states.get(target)
    await controller.push(
        *[
            parse_event({"op": "log", "id": device, "time": 1000, "key": key})
            for device, key in [
                (1005, "singleClick:/status/active"),
                (1006, "singleClick:/status/active"),
                (1005, "tripleClick:/status/input"),
                (9999, "singleClick:/status/input"),
            ]
        ]
    )
    await hass.async_block_till_done()
    assert hass.states.get(target) == before
    assert "Ignoring unknown switch gesture tripleClick" in caplog.text
    for gesture in ["doubleClick", "singleClick"]:
        await controller.push(
            parse_event({"op": "log", "id": 1005, "time": 1000, "key": f"{gesture}:/status/input"})
        )
        await hass.async_block_till_done()
    assert ATTR_MULTI_PRESS_COUNT not in hass.states.get(target).attributes
    hub = loaded_entry.runtime_data
    await hass.config_entries.async_unload(loaded_entry.entry_id)
    assert hub._gesture_listeners == {}
