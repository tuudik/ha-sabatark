"""Tests for access devices modelled as locks."""

import pytest
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sabatark import AgatarkError, parse_event

from .conftest import FakeController, entity_id


@pytest.fixture
async def lock_entry(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set up the integration with the access device modelled as a lock."""
    hass.config_entries.async_update_entry(
        config_entry, options={"access": {"1010": {"model": "lock"}}}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


async def test_lock(
    hass: HomeAssistant, controller: FakeController, lock_entry: MockConfigEntry
) -> None:
    target = entity_id(hass, "lock", 1010, "lock")
    assert hass.states.get(target).state == "locked"
    assert controller.writes == []
    for service, value in [("unlock", False), ("lock", True)]:
        await hass.services.async_call("lock", service, {ATTR_ENTITY_ID: target}, blocking=True)
        assert controller.writes[-1] == ("devices", 1010, {"status": {"locked": value}})
    assert hass.states.get(target).state == "locked"
    await controller.push(parse_event({"id": 1010, "status": {"locked": False}}))
    await hass.async_block_till_done()
    assert hass.states.get(target).state == "unlocked"
    await controller.push(parse_event({"id": 1010, "status": {"locked": None}}))
    await hass.async_block_till_done()
    assert hass.states.get(target).state == "unknown"


async def test_lock_write_failure(
    hass: HomeAssistant, controller: FakeController, lock_entry: MockConfigEntry
) -> None:
    controller.write_error = AgatarkError("Synthetic write failure", status=403)
    with pytest.raises(HomeAssistantError, match="Synthetic write failure"):
        await hass.services.async_call(
            "lock", "unlock", {ATTR_ENTITY_ID: entity_id(hass, "lock", 1010, "lock")}, blocking=True
        )
