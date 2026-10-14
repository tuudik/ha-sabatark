"""Tests for per-output access impulse buttons."""

import pytest
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import SITE_ID, FakeController, entity_id

PATHS = ["status.locked", "status.output2", "status.output3"]


@pytest.mark.parametrize(
    ("language", "labels"),
    [("en", ["Impulse", "Impulse 2", "Impulse 3"]), ("et", ["Impulss", "Impulss 2", "Impulss 3"])],
)
async def test_buttons(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    language: str,
    labels: list[str],
) -> None:
    hass.config.language = language
    hass.config_entries.async_update_entry(
        config_entry, options={"access": {"1010": {"model": "buttons", "paths": PATHS}}}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert controller.writes == []
    assert (
        er.async_get(hass).async_get_entity_id("lock", "sabatark", f"{SITE_ID}_1010_lock") is None
    )
    for path, label in zip(PATHS, labels, strict=True):
        key = path.removeprefix("status.")
        target = entity_id(hass, "button", 1010, f"button_{key}")
        assert hass.states.get(target).attributes["friendly_name"] == f"Front door lock {label}"
        await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: target}, blocking=True)
        assert controller.writes[-1] == ("devices", 1010, {"status": {key: False}})
