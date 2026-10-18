"""Tests for controller reachability reported by the client."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from sabatark import UplinkError

from custom_components.sabatark.const import UNAVAILABLE_GRACE

from .conftest import HOST, FakeController, entity_id

LOST = "Lost connection to the controller"
RESTORED = "Connection to the controller restored"


def _messages(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("custom_components.sabatark") and record.levelno == level
    ]


async def _advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_connection_loss_and_recovery(
    hass: HomeAssistant,
    controller: FakeController,
    loaded_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
) -> None:
    client = controller.clients[-1]
    light = entity_id(hass, "light", 1001, "light")
    door = entity_id(hass, "binary_sensor", 1010, "door")
    assert hass.states.get(light).state == STATE_OFF
    caplog.clear()

    client.on_connection_change(False)
    client.on_connection_change(False)
    await hass.async_block_till_done()
    assert loaded_entry.runtime_data.connected
    assert hass.states.get(light).state == STATE_OFF
    assert _messages(caplog, logging.WARNING) == []

    await _advance(hass, freezer, UNAVAILABLE_GRACE + 1)
    assert not loaded_entry.runtime_data.connected
    assert hass.states.get(light).state == STATE_UNAVAILABLE
    assert hass.states.get(door).state == STATE_UNAVAILABLE
    assert _messages(caplog, logging.WARNING) == [LOST]
    assert _messages(caplog, logging.INFO) == []

    client.on_connection_change(True)
    client.on_connection_change(True)
    await hass.async_block_till_done()
    assert loaded_entry.runtime_data.connected
    assert hass.states.get(light).state == STATE_OFF
    assert hass.states.get(door).state == STATE_OFF
    assert _messages(caplog, logging.WARNING) == [LOST]
    assert _messages(caplog, logging.INFO) == [RESTORED]
    assert HOST not in caplog.text
    assert "session-" not in caplog.text


async def test_short_connection_loss_keeps_entities_available(
    hass: HomeAssistant,
    controller: FakeController,
    loaded_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
    freezer: FrozenDateTimeFactory,
) -> None:
    client = controller.clients[-1]
    light = entity_id(hass, "light", 1001, "light")
    caplog.clear()

    client.on_connection_change(False)
    await _advance(hass, freezer, UNAVAILABLE_GRACE - 5)
    client.on_connection_change(True)
    await _advance(hass, freezer, 10)
    assert loaded_entry.runtime_data.connected
    assert hass.states.get(light).state == STATE_OFF
    assert _messages(caplog, logging.WARNING) == []
    assert _messages(caplog, logging.INFO) == []


async def test_reachable_controller_with_failed_stream_stays_unavailable(
    hass: HomeAssistant,
    controller: FakeController,
    loaded_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    client = controller.clients[-1]
    light = entity_id(hass, "light", 1001, "light")
    controller.read_error = UplinkError("HTTP 504", status=504)
    await controller.push(UplinkError("HTTP 504", status=504))
    await hass.async_block_till_done()
    client.on_connection_change(False)
    client.on_connection_change(True)
    await _advance(hass, freezer, UNAVAILABLE_GRACE + 1)
    assert not loaded_entry.runtime_data.connected
    assert hass.states.get(light).state == STATE_UNAVAILABLE


async def test_unknown_initial_state_is_available(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    assert controller.clients[-1].connected is None
    assert loaded_entry.runtime_data.connected
