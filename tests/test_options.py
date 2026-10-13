"""Tests for access modelling options."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sabatark.options_flow import status_key

from .conftest import FakeController, entity_id


@pytest.mark.parametrize("model", ["lock", "cover", "buttons"])
async def test_options_round_trip(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry, model: str
) -> None:
    controller.devices[9]["status"]["output2"] = True
    extra = deepcopy(controller.devices[9])
    extra.update(id=1020, name="Side gate")
    controller.devices.append(extra)
    preserved = {"model": "buttons", "paths": ["status.locked"]}
    hass.config_entries.async_update_entry(config_entry, options={"access": {"1020": preserved}})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"device": "1010"}
    )
    assert result["step_id"] == "model"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"model": model})
    expected = {"model": model, "paths": ["status.locked"]}
    if model == "buttons":
        assert result["step_id"] == "buttons"
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"paths": []})
        assert result["errors"] == {"paths": "no_paths"}
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"paths": ["status.locked", "status.output2"]}
        )
        expected["paths"] = ["status.locked", "status.output2"]
    elif model == "cover":
        assert result["step_id"] == "cover"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"path": "status.locked", "state_device": "1007"}
        )
        assert result["step_id"] == "state"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"state_path": "status.open"}
        )
        expected.update(state_device=1007, state_path="status.open")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert dict(config_entry.options) == {"access": {"1010": expected, "1020": preserved}}
    assert controller.writes == []
    key = "button_locked" if model == "buttons" else model
    platform = "button" if model == "buttons" else model
    assert hass.states.get(entity_id(hass, platform, 1010, key)) is not None
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"device": "1010"}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    if model == "lock":
        assert result["type"] is FlowResultType.CREATE_ENTRY
    else:
        assert result["step_id"] == ("buttons" if model == "buttons" else "cover")


async def test_no_access_devices(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    controller.devices = [device for device in controller.devices if device["type"] != "access"]
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["reason"] == "no_access_devices"


async def test_not_loaded(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["reason"] == "not_loaded"


async def test_no_state_devices(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    controller.devices = [device for device in controller.devices if device["type"] == "access"]
    controller.devices[0]["status"] = {"online": True}
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"device": "1010"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"model": "cover"}
    )
    assert result["reason"] == "no_state_devices"
    assert dict(config_entry.options) == {}


async def test_unchanged_options_do_not_reload(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    options = {"access": {"1010": {"model": "lock", "paths": ["status.locked"]}}}
    hass.config_entries.async_update_entry(config_entry, options=options)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock) as reload:
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"device": "1010"}
        )
        await hass.config_entries.options.async_configure(result["flow_id"], {"model": "lock"})
        await hass.async_block_till_done()
        reload.assert_not_called()


@pytest.mark.parametrize(
    "path", ["locked", "status.", "conf.locked", "status.nested.locked", "status./locked"]
)
def test_invalid_output_path(path: str) -> None:
    with pytest.raises(ValueError):
        status_key(path)
