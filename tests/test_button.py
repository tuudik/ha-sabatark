"""Tests for per-output access pulse buttons."""

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import SITE_ID, FakeController, entity_id


async def test_buttons(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    hass.config_entries.async_update_entry(
        config_entry,
        options={
            "access": {
                "1010": {
                    "model": "buttons",
                    "paths": ["status.locked", "status.output2", "status.output3"],
                }
            }
        },
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert controller.writes == []
    assert (
        er.async_get(hass).async_get_entity_id("lock", "sabatark", f"{SITE_ID}_1010_lock") is None
    )
    for key, label in [
        ("locked", "Open"),
        ("output2", "Open (secondary)"),
        ("output3", "Open (status.output3)"),
    ]:
        target = entity_id(hass, "button", 1010, f"button_{key}")
        assert hass.states.get(target).attributes["friendly_name"].endswith(label)
        await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: target}, blocking=True)
        assert controller.writes[-1] == ("devices", 1010, {"status": {key: False}})
