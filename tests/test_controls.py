"""Tests for parsing ui-declared controls."""

from __future__ import annotations

from typing import Any

import pytest
from sabatark import Device

from custom_components.sabatark.controls import (
    Controls,
    Level,
    brightness_to_level,
    level_to_brightness,
    parse_controls,
)

OPEN_BUTTON = "#icont#Open#door#btn:true=closed,false=open"


def _device(device_id: int, ui: Any) -> Device:
    return Device.from_dict({"id": device_id, "type": "test", "status": {}, "ui": ui})


def _parse(ui: Any, *templates: Device) -> Controls:
    devices = {template.id: template for template in templates}
    return parse_controls(_device(1, ui), devices)


def test_no_ui() -> None:
    assert parse_controls(Device.from_dict({"id": 1}), {}) == Controls()
    assert _parse(["status.output#onoff"]) == Controls()


def test_light_onoff() -> None:
    assert _parse({"i1": ["status.output#onoff#Light"]}) == Controls(onoff="status.output")


def test_dimmer() -> None:
    controls = _parse(
        {
            "i1": ["status.on#onoff#Power"],
            "i2": ["status.target#level#Brightness#%#0:100:5"],
        }
    )
    assert controls.onoff == "status.on"
    assert controls.level == Level("status.target", 0, 100, 5)
    assert controls.buttons == []


def test_level_without_range_is_ignored() -> None:
    assert _parse({"i1": ["status.target#level#Brightness"]}).level is None
    assert _parse({"i1": ["status.target#level#Brightness#5:5:1"]}).level is None
    assert _parse({"i1": ["status.target#level#Brightness#0:10:20"]}).level is None


def test_first_declaration_wins_in_item_order() -> None:
    controls = _parse(
        {
            "i10": ["status.later#onoff"],
            "i2": ["status.first#onoff", "status.second#onoff"],
        }
    )
    assert controls.onoff == "status.first"


def test_buttons() -> None:
    controls = _parse(
        {
            "i1": [f"status.locked{OPEN_BUTTON}", "status.locked#icont#Locked#lock"],
            "i2": [f"status.output2{OPEN_BUTTON}", f"status.locked{OPEN_BUTTON}"],
            "i3": ["status.output3#icont#Busy#btn:true=busy"],
        }
    )
    assert controls.buttons == ["status.locked", "status.output2"]


def test_template_reference() -> None:
    template = _device(900, {"i1": ["status.output#onoff#Light"], "i2": ["status.x#onoff"]})
    controls = _parse({"i1": 900, "i3": ["status.target#level#Level#0:100:1"]}, template)
    assert controls == Controls(onoff="status.output", level=Level("status.target", 0, 100, 1))


def test_nested_template_reference() -> None:
    inner = _device(902, {"i1": ["status.on#onoff"]})
    middle = _device(901, {"i1": 902})
    assert _parse({"i1": 901}, middle, inner).onoff == "status.on"


def test_template_depth_limit() -> None:
    chain = [_device(900 + n, {"i1": 901 + n}) for n in range(3)]
    chain.append(_device(903, {"i1": ["status.on#onoff"]}))
    assert _parse({"i1": 900}, *chain).onoff is None
    assert _parse({"i1": 901}, *chain).onoff == "status.on"


@pytest.mark.parametrize(
    "ui",
    [
        {"i1": 999},
        {"i1": 900},
        {"i1": True},
        {"i1": 905},
    ],
)
def test_unresolvable_templates_are_skipped(ui: dict[str, Any]) -> None:
    loop = _device(905, {"i1": 905})
    assert _parse(ui, _device(900, {"i2": ["status.on#onoff"]}), loop) == Controls()


def test_junk_entries_are_ignored() -> None:
    controls = _parse(
        {
            "i1": [
                "status.name#editt#Name",
                "status.count#editn#Count",
                "status.mode#mode#Mode",
                "status.output#icon#Icon",
                "{status.a && status.b}#onoff",
                "id#onoff#Id",
                "idle.output#onoff",
                "status#onoff#Whole status",
                "setup.output#onoff",
                "status.deep.path#onoff",
                "status.output",
                "",
                42,
                None,
            ],
            "label": ["status.wrong#onoff"],
            "i2": "status.output#onoff#Single",
        }
    )
    assert controls == Controls(onoff="status.output")


@pytest.mark.parametrize(
    ("value", "brightness"),
    [(100, 255), (50, 128), (5, 13), (0, 1), (None, None), (True, None), ("50", None)],
)
def test_level_to_brightness(value: Any, brightness: int | None) -> None:
    assert level_to_brightness(Level("status.target", 0, 100, 5), value) == brightness


@pytest.mark.parametrize(
    ("brightness", "value"),
    [(255, 100), (128, 50), (1, 5), (12, 5), (13, 5), (20, 10), (250, 100)],
)
def test_brightness_to_level(brightness: int, value: int) -> None:
    result = brightness_to_level(Level("status.target", 0, 100, 5), brightness)
    assert result == value
    assert isinstance(result, int)


def test_brightness_to_level_with_offset_range() -> None:
    assert brightness_to_level(Level("status.target", 10, 20, 0.5), 255) == 20
    assert brightness_to_level(Level("status.target", 10, 20, 0.5), 128) == 15
    assert brightness_to_level(Level("status.target", 10, 20, 0.5), 140) == 15.5
