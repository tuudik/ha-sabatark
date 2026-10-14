"""Tests for entities driven by ui-declared controls."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sabatark import parse_event

from .conftest import SITE_ID, FakeController, entity_id

OPEN_BUTTON = "#icont#Open#door#btn:true=closed,false=open"


def _add(controller: FakeController, device_id: int, type_: str, status: dict, ui: Any) -> None:
    controller.devices.append(
        {
            "id": device_id,
            "name": f"Test {type_} {device_id}",
            "type": type_,
            "roomId": 100,
            "siteId": SITE_ID,
            "usage": {type_: [""]},
            "status": {"online": True, **status},
            "ui": ui,
        }
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _light(hass: HomeAssistant, entity: str, **data: Any) -> None:
    await hass.services.async_call(
        "light", "turn_on", {ATTR_ENTITY_ID: entity, **data}, blocking=True
    )


async def test_dimmer_light(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    _add(
        controller,
        1101,
        "outputPwm",
        {"on": True, "target": 60, "level": 40},
        {
            "i1": ["status.on#onoff#Power"],
            "i2": ["status.target#level#Brightness#%#0:100:5"],
            "i3": ["status.level#editn#Level"],
        },
    )
    await _setup(hass, config_entry)
    target = entity_id(hass, "light", 1101, "light")
    state = hass.states.get(target)
    assert state.state == STATE_ON
    assert state.attributes["supported_color_modes"] == [ColorMode.BRIGHTNESS]
    assert state.attributes["color_mode"] == ColorMode.BRIGHTNESS
    assert state.attributes[ATTR_BRIGHTNESS] == 102

    await _light(hass, target, brightness=128)
    await _light(hass, target)
    await hass.services.async_call("light", "turn_off", {ATTR_ENTITY_ID: target}, blocking=True)
    assert controller.writes == [
        ("devices", 1101, {"status": {"on": True, "target": 50}}),
        ("devices", 1101, {"status": {"on": True}}),
        ("devices", 1101, {"status": {"on": False}}),
    ]

    await controller.push(parse_event({"id": 1101, "status": {"level": 55}}))
    await hass.async_block_till_done()
    assert hass.states.get(target).attributes[ATTR_BRIGHTNESS] == 140
    await controller.push(parse_event({"id": 1101, "status": {"on": False}}))
    await hass.async_block_till_done()
    assert hass.states.get(target).state == STATE_OFF


async def test_dimmer_brightness_falls_back_to_target(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    _add(
        controller,
        1102,
        "outputPwm",
        {"output": True, "target": 100},
        {"i1": 1103, "i2": ["status.target#level#Brightness#0:100:5"]},
    )
    controller.devices.append(
        {"id": 1103, "type": "template", "ui": {"i1": ["status.output#onoff#Light"]}}
    )
    await _setup(hass, config_entry)
    target = entity_id(hass, "light", 1102, "light")
    assert hass.states.get(target).attributes[ATTR_BRIGHTNESS] == 255
    await _light(hass, target, brightness=3)
    await hass.services.async_call("light", "turn_off", {ATTR_ENTITY_ID: target}, blocking=True)
    assert controller.writes == [
        ("devices", 1102, {"status": {"output": True, "target": 5}}),
        ("output", 1102, False),
    ]


async def test_declared_onoff_path(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    _add(controller, 1104, "output", {"output": False, "relay": True}, {"i1": 1105})
    _add(
        controller, 1105, "output", {"output": True, "relay": False}, {"i1": ["status.relay#onoff"]}
    )
    await _setup(hass, config_entry)
    switch = entity_id(hass, "switch", 1104, "switch")
    assert hass.states.get(switch).state == STATE_ON
    assert hass.states.get(entity_id(hass, "switch", 1105, "switch")).state == STATE_OFF
    await hass.services.async_call("switch", "turn_off", {ATTR_ENTITY_ID: switch}, blocking=True)
    assert controller.writes == [("devices", 1104, {"status": {"relay": False}})]
    light = entity_id(hass, "light", 1001, "light")
    assert hass.states.get(light).attributes["supported_color_modes"] == [ColorMode.ONOFF]


async def test_gate_defaults_to_declared_buttons(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    _add(
        controller,
        1106,
        "access",
        {"locked": True, "output2": True},
        {"i1": 1107, "i2": [f"status.output2{OPEN_BUTTON}"]},
    )
    controller.devices.append(
        {"id": 1107, "type": "template", "ui": {"i1": [f"status.locked{OPEN_BUTTON}"]}}
    )
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("lock", "sabatark", f"{SITE_ID}_1106_lock") is None
    for key in ("locked", "output2"):
        button = entity_id(hass, "button", 1106, f"button_{key}")
        await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: button}, blocking=True)
        assert controller.writes[-1] == ("devices", 1106, {"status": {key: False}})


async def test_access_without_options_defaults_to_buttons(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    _add(controller, 1108, "access", {"locked": True}, {"i1": [f"status.locked{OPEN_BUTTON}"]})
    await _setup(hass, config_entry)
    registry = er.async_get(hass)
    for device_id in (1108, 1010):
        assert (
            registry.async_get_entity_id("lock", "sabatark", f"{SITE_ID}_{device_id}_lock") is None
        )
        assert (
            registry.async_get_entity_id("cover", "sabatark", f"{SITE_ID}_{device_id}_cover")
            is None
        )
        button = entity_id(hass, "button", device_id, "button_locked")
        await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: button}, blocking=True)
        assert controller.writes[-1] == ("devices", device_id, {"status": {"locked": False}})


async def test_stored_access_options_are_authoritative(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    _add(
        controller,
        1106,
        "access",
        {"locked": True, "output2": True},
        {"i1": [f"status.locked{OPEN_BUTTON}", f"status.output2{OPEN_BUTTON}"]},
    )
    hass.config_entries.async_update_entry(
        config_entry, options={"access": {"1106": {"model": "lock"}}}
    )
    await _setup(hass, config_entry)
    assert hass.states.get(entity_id(hass, "lock", 1106, "lock")).state == "locked"
    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id("button", "sabatark", f"{SITE_ID}_1106_button_locked") is None
    )


async def test_options_offer_declared_defaults(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    _add(
        controller,
        1106,
        "access",
        {"locked": True, "open": False},
        {"i1": [f"status.locked{OPEN_BUTTON}", f"status.output2{OPEN_BUTTON}"]},
    )
    await _setup(hass, config_entry)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"device": "1106"}
    )
    assert _default(result, "model") == "buttons"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"model": "cover"}
    )
    assert result["step_id"] == "cover"
    assert _default(result, "path") == "status.locked"
    assert _default(result, "state_device") == "1106"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"path": "status.output2", "state_device": "1106"}
    )
    assert result["step_id"] == "state"
    assert _default(result, "state_path") == "status.open"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"state_path": "status.open"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options["access"]["1106"] == {
        "model": "cover",
        "paths": ["status.output2"],
        "state_device": 1106,
        "state_path": "status.open",
    }


def _default(result: dict[str, Any], name: str) -> Any:
    for key in result["data_schema"].schema:
        if key == name:
            return key.default()
    raise AssertionError(name)
