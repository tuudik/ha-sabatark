"""Tests for pulse-operated garage covers."""

import pytest
from homeassistant.components.cover import DATA_COMPONENT
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sabatark import parse_event

from .conftest import SITE_ID, FakeController, entity_id

PULSE = ("devices", 1010, {"status": {"output2": False}})


async def _setup_cover(
    hass: HomeAssistant, config_entry: MockConfigEntry, source: int, state_path: str
) -> str:
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
    return entity_id(hass, "cover", 1010, "cover")


async def _call(hass: HomeAssistant, service: str, target: str) -> None:
    await hass.services.async_call("cover", service, {ATTR_ENTITY_ID: target}, blocking=True)


@pytest.mark.parametrize("state_path", ["status.open", "status.active"])
async def test_cover_state_and_pulses(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry, state_path: str
) -> None:
    source = 1007 if state_path == "status.open" else 1006
    target = await _setup_cover(hass, config_entry, source, state_path)
    assert (
        er.async_get(hass).async_get_entity_id("lock", "sabatark", f"{SITE_ID}_1010_lock") is None
    )
    assert hass.states.get(target).state == "closed"
    assert hass.states.get(target).attributes["device_class"] == "garage"
    assert controller.writes == []
    await _call(hass, "close_cover", target)
    assert controller.writes == []
    await _call(hass, "open_cover", target)
    assert controller.writes == [PULSE]
    await _call(hass, "toggle", target)
    assert controller.writes == [PULSE] * 2
    key = state_path.split(".")[1]
    await controller.push(parse_event({"id": source, "status": {key: True}}))
    await hass.async_block_till_done()
    assert hass.states.get(target).state == "open"
    await _call(hass, "open_cover", target)
    assert controller.writes == [PULSE] * 2
    await _call(hass, "close_cover", target)
    assert controller.writes == [PULSE] * 3
    await controller.push(parse_event({"id": source, "status": {key: None}}))
    await hass.async_block_till_done()
    assert hass.states.get(target).state == "unknown"
    for service in ("open_cover", "close_cover"):
        with pytest.raises(HomeAssistantError) as raised:
            await _call(hass, service, target)
        assert raised.value.translation_key == "cover_state_unknown"
        assert str(raised.value).startswith("The garage door state is unknown")
    assert controller.writes == [PULSE] * 3
    await _call(hass, "toggle", target)
    assert controller.writes == [PULSE] * 4
    await controller.push(parse_event({"id": source, "status": {"online": False}}))
    await hass.async_block_till_done()
    assert hass.states.get(target).state == "unavailable"
    hub = config_entry.runtime_data
    await hass.config_entries.async_unload(config_entry.entry_id)
    assert hub._device_listeners == {}


async def test_unavailable_cover_refuses_open_and_close(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    target = await _setup_cover(hass, config_entry, 1007, "status.open")
    await controller.push(parse_event({"id": 1007, "status": {"online": False}}))
    await hass.async_block_till_done()
    cover = hass.data[DATA_COMPONENT].get_entity(target)
    assert cover is not None and not cover.available
    with pytest.raises(HomeAssistantError):
        await cover.async_open_cover()
    with pytest.raises(HomeAssistantError):
        await cover.async_close_cover()
    assert controller.writes == []


async def test_cover_door_sensor_is_a_garage_door(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    await _setup_cover(hass, config_entry, 1010, "status.open")
    door = entity_id(hass, "binary_sensor", 1010, "door")
    assert hass.states.get(door).attributes["device_class"] == "garage_door"
    assert hass.states.get(door).state == "off"
