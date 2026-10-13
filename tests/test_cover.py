"""Tests for pulse-operated garage covers."""

import pytest
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sabatark import parse_event

from .conftest import SITE_ID, FakeController, entity_id


@pytest.mark.parametrize("state_path", ["status.open", "status.active"])
async def test_cover_state_and_pulses(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry, state_path: str
) -> None:
    source = 1007 if state_path == "status.open" else 1006
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            "access": {
                "1010": {
                    "model": "cover",
                    "paths": ["status.output2"],
                    "state_device": source,
                    "state_path": state_path,
                }
            }
        },
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    target = entity_id(hass, "cover", 1010, "cover")
    assert (
        er.async_get(hass).async_get_entity_id("lock", "sabatark", f"{SITE_ID}_1010_lock") is None
    )
    assert hass.states.get(target).state == "closed"
    assert hass.states.get(target).attributes["device_class"] == "garage"
    assert controller.writes == []
    for service in ["open_cover", "close_cover", "toggle"]:
        await hass.services.async_call("cover", service, {ATTR_ENTITY_ID: target}, blocking=True)
    assert controller.writes == [("devices", 1010, {"status": {"output2": False}})] * 3
    assert hass.states.get(target).state == "closed"
    key = state_path.split(".")[1]
    await controller.push(parse_event({"id": source, "status": {key: True}}))
    await hass.async_block_till_done()
    assert hass.states.get(target).state == "open"
    await controller.push(parse_event({"id": source, "status": {key: None}}))
    await hass.async_block_till_done()
    assert hass.states.get(target).state == "unknown"
    await controller.push(parse_event({"id": source, "status": {"online": False}}))
    await hass.async_block_till_done()
    assert hass.states.get(target).state == "unavailable"
    hub = config_entry.runtime_data
    await hass.config_entries.async_unload(config_entry.entry_id)
    assert hub._device_listeners == {}
