"""Controls declared by a device's user interface description."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from sabatark import Device

MAX_TEMPLATE_DEPTH = 3
DEFAULT_ONOFF = "status.output"

_RANGE = re.compile(r"^-?\d+(?:\.\d+)?:-?\d+(?:\.\d+)?:\d+(?:\.\d+)?$")
_ITEM_KEY = re.compile(r"^i\d+$")


class Level(NamedTuple):
    """A slider control: status path and its range."""

    path: str
    min: float
    max: float
    step: float


@dataclass(frozen=True)
class Controls:
    """The on/off path, level slider and action buttons of a device."""

    onoff: str | None = None
    level: Level | None = None
    buttons: list[str] = field(default_factory=list)


def status_key(path: str) -> str | None:
    """Return the key of a direct status path, or None for any other path."""
    prefix, separator, key = path.partition(".")
    if prefix != "status" or not separator or not key or "." in key or "/" in key:
        return None
    return key


def parse_controls(device: Device, devices: Mapping[int, Device]) -> Controls:
    """Return the controls declared in a device's ui, resolving template references."""
    ui = device.raw.get("ui")
    if not isinstance(ui, Mapping):
        return Controls()
    onoff: str | None = None
    level: Level | None = None
    buttons: list[str] = []
    for key in sorted((key for key in ui if _ITEM_KEY.match(str(key))), key=lambda k: int(k[1:])):
        for entry in _resolve(ui[key], key, devices, 0):
            parts = entry.split("#")
            if len(parts) < 2 or status_key(parts[0]) is None:
                continue
            path, widget = parts[0], parts[1]
            if widget == "onoff":
                onoff = onoff or path
            elif widget == "level" and level is None:
                level = _level(path, parts[2:])
            elif _is_button(widget, entry) and path not in buttons:
                buttons.append(path)
    return Controls(onoff=onoff, level=level, buttons=buttons)


def _resolve(value: Any, key: str, devices: Mapping[int, Device], depth: int) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, int) and not isinstance(value, bool) and depth < MAX_TEMPLATE_DEPTH:
        template = devices.get(value)
        ui = template.raw.get("ui") if template is not None else None
        if isinstance(ui, Mapping) and key in ui:
            return _resolve(ui[key], key, devices, depth + 1)
    return []


def _is_button(widget: str, entry: str) -> bool:
    return widget == "icont" and "btn" in entry and ",false=open" in entry


def _level(path: str, fields: list[str]) -> Level | None:
    for item in fields:
        if _RANGE.match(item):
            low, high, step = (float(part) for part in item.split(":"))
            if high > low and 0 < step <= high - low:
                return Level(path, low, high, step)
    return None


def level_to_brightness(level: Level, value: Any) -> int | None:
    """Return the 1..255 brightness of a level value, or None when it is not numeric."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    fraction = (value - level.min) / (level.max - level.min)
    return max(1, min(255, round(fraction * 255)))


def brightness_to_level(level: Level, brightness: int) -> int | float:
    """Return the level value for a 1..255 brightness, snapped to the slider's step."""
    steps = round((brightness / 255) * (level.max - level.min) / level.step)
    span = int((level.max - level.min) / level.step)
    value = level.min + max(1, min(span, steps)) * level.step
    return int(value) if float(value).is_integer() else value
