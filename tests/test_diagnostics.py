"""Tests for diagnostic redaction."""

import json

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sabatark.diagnostics import async_get_config_entry_diagnostics

from .conftest import EMAIL, HOST, FakeController


async def test_redaction(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    original = dict(loaded_entry.data)
    report = await async_get_config_entry_diagnostics(hass, loaded_entry)
    for key in ["host", "email", "token", "user_id", "session"]:
        assert report["data"][key] == REDACTED
    assert report["title"] == REDACTED
    assert report["unique_id"] == REDACTED
    hub = loaded_entry.runtime_data
    assert report["hub"]["site"]["name"] == REDACTED
    assert report["hub"]["device_count"] == len(hub.devices)
    assert report["hub"]["room_count"] == len(hub.rooms)
    for device in report["hub"]["devices"]:
        assert device["name"] == REDACTED
        source = hub.devices[device["id"]]
        assert device["type"] == source.type
        assert device["usage"] == source.usage
        assert device["status"] == source.status
    assert all(room["name"] == REDACTED for room in report["hub"]["rooms"])
    serialized = json.dumps(report)
    for secret in [
        HOST,
        EMAIL,
        original["token"],
        original["session"]["authorization"],
        loaded_entry.title,
        *[device.name for device in hub.devices.values()],
        *[room.name for room in hub.rooms.values()],
    ]:
        assert secret not in serialized
    assert dict(loaded_entry.data) == original


async def test_unloaded_and_nested_redaction(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            "metadata": {
                "authorization": "fake-secret",
                "userId": 99,
                "name": "Example label",
                "type": "access",
                "status": {"open": True},
            }
        },
    )
    report = await async_get_config_entry_diagnostics(hass, config_entry)
    assert "hub" not in report
    metadata = report["options"]["metadata"]
    assert metadata == {
        "authorization": REDACTED,
        "userId": REDACTED,
        "name": REDACTED,
        "type": "access",
        "status": {"open": True},
    }
