"""Tests for removing devices the hub no longer provides."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryDisabler
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sabatark import async_remove_config_entry_device
from custom_components.sabatark.const import DOMAIN

from .conftest import SITE_ID, FakeController

STALE = (DOMAIN, f"{SITE_ID}_1999")


def _device(hass: HomeAssistant, entry: MockConfigEntry, identifier: str) -> dr.DeviceEntry:
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, identifier), entry.entry_id)
    assert device is not None
    return device


async def test_stale_device_can_be_removed(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    stale = dr.async_get(hass).async_get_or_create(
        config_entry_id=loaded_entry.entry_id, identifiers={STALE}, name="Old detector"
    )
    assert await async_remove_config_entry_device(hass, loaded_entry, stale) is True


async def test_live_device_cannot_be_removed(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    light = _device(hass, loaded_entry, f"{SITE_ID}_1001")
    assert await async_remove_config_entry_device(hass, loaded_entry, light) is False


async def test_hub_device_cannot_be_removed(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    hub = _device(hass, loaded_entry, str(SITE_ID))
    assert await async_remove_config_entry_device(hass, loaded_entry, hub) is False


async def test_setup_removes_stale_devices_and_keeps_live_ones(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    registry = dr.async_get(hass)
    other_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Cabin",
        unique_id="41_20",
        disabled_by=ConfigEntryDisabler.USER,
    )
    other_entry.add_to_hass(hass)
    stale = registry.async_get_or_create(
        config_entry_id=config_entry.entry_id, identifiers={STALE}, name="Old detector"
    )
    live = registry.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, f"{SITE_ID}_1001")},
        name="Kitchen light",
    )
    foreign = registry.async_get_or_create(
        config_entry_id=other_entry.entry_id,
        identifiers={(DOMAIN, "20_1999")},
        name="Cabin detector",
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(stale.id) is None
    assert registry.async_get(live.id) is not None
    assert registry.async_get(foreign.id) is not None
    assert registry.async_get_device_by_identifier((DOMAIN, str(SITE_ID)), config_entry.entry_id)
