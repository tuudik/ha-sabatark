"""Tests for restoring outputs after an I/O module loses power."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Generator
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from sabatark import AgatarkError, parse_event

from custom_components.sabatark.const import DOMAIN
from custom_components.sabatark.diagnostics import async_get_config_entry_diagnostics
from custom_components.sabatark.restore import EVENT_OUTPUTS_RESTORED, RestoreManager

from .conftest import HOST, SITE_ID, FakeController

MODULE = 3001
DIMMER_MODULE = 3002
DIMMER = 1101


def _conf(module_id: int) -> list[dict[str, Any]]:
    return [{"id": module_id, "path": "/outputs/o1", "mode": "output", "target": "/status/output"}]


def _module(module_id: int, uptime: int = 5000) -> dict[str, Any]:
    return {
        "id": module_id,
        "name": f"Relay module {module_id}",
        "type": "relayModule_Modbus",
        "siteId": SITE_ID,
        "parentId": 1099,
        "usage": None,
        "status": {"online": True, "uptime": uptime},
    }


def _status(controller: FakeController, device_id: int) -> dict[str, Any]:
    return next(item for item in controller.devices if item["id"] == device_id)["status"]


def _prepare(controller: FakeController) -> None:
    """Put the lights, the pump, a dimmer and the access device on relay modules."""
    controller.devices += [_module(MODULE), _module(DIMMER_MODULE)]
    for device in controller.devices:
        if device["id"] in (1001, 1002, 1003, 1004, 1010):
            device["conf"] = _conf(MODULE)
    _status(controller, 1001)["output"] = True
    _status(controller, 1002)["output"] = True
    _status(controller, 1003)["output"] = True
    _status(controller, 1004)["output"] = True
    controller.devices.append(
        {
            "id": DIMMER,
            "name": "Lounge dimmer",
            "type": "outputPwm",
            "roomId": 100,
            "siteId": SITE_ID,
            "usage": {"light": [""]},
            "status": {"online": True, "on": True, "target": 60, "level": 60},
            "conf": _conf(DIMMER_MODULE),
            "ui": {
                "i1": ["status.on#onoff#Power"],
                "i2": ["status.target#level#Brightness#%#0:100:5"],
            },
        }
    )


def _store_key(entry: MockConfigEntry) -> str:
    return f"sabatark.{entry.entry_id}.restore"


@pytest.fixture(autouse=True)
def no_pause() -> Generator[None]:
    """Remove the pause between restore writes."""
    with patch("custom_components.sabatark.restore.WRITE_INTERVAL", 0):
        yield


@pytest.fixture
def notifications() -> Generator[list[dict[str, Any]]]:
    """Capture persistent notifications."""
    created: list[dict[str, Any]] = []

    def create(hass: HomeAssistant, message: str, title: str | None = None, **kwargs: Any) -> None:
        created.append({"message": message, "title": title, **kwargs})

    with patch.object(persistent_notification, "async_create", create):
        yield created


async def _start(
    hass: HomeAssistant, controller: FakeController, entry: MockConfigEntry, selected: list[int]
) -> RestoreManager:
    hass.config_entries.async_update_entry(
        entry, options={"restore": {"policy": "last_state", "devices": selected}}
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    manager = entry.runtime_data.restore
    assert manager is not None
    return manager


async def _setup(
    hass: HomeAssistant, controller: FakeController, entry: MockConfigEntry, selected: list[int]
) -> RestoreManager:
    _prepare(controller)
    return await _start(hass, controller, entry, selected)


def _stored(entry: MockConfigEntry, hass_storage: dict[str, Any], data: dict[str, Any]) -> None:
    hass_storage[_store_key(entry)] = {
        "version": 1,
        "minor_version": 1,
        "key": _store_key(entry),
        "data": data,
    }


def _power_loss_sensor(hass: HomeAssistant) -> str:
    found = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{SITE_ID}_last_power_loss")
    assert found is not None
    return found


async def _push(controller: FakeController, device_id: int, **status: Any) -> None:
    await controller.push(parse_event({"id": device_id, "status": status}))


async def _all_off(controller: FakeController) -> None:
    for device_id in (1001, 1002, 1003, 1004):
        await _push(controller, device_id, output=False)


async def _advance(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_module_return_restores_selected_differing_outputs(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    notifications: list[dict[str, Any]],
) -> None:
    events = async_capture_events(hass, EVENT_OUTPUTS_RESTORED)
    manager = await _setup(hass, controller, config_entry, [1001, 1003, 1004])
    assert manager.memory == {"1001": {"on": True}, "1003": {"on": True}, "1004": {"on": True}}
    lost_at = dt_util.utcnow()

    await _push(controller, MODULE, online=False)
    await _all_off(controller)
    await _advance(hass, freezer, 600)
    await _push(controller, MODULE, online=True, uptime=12)
    await _all_off(controller)
    await _push(controller, 1003, output=True)
    assert manager.memory["1001"] == {"on": True}
    await _advance(hass, freezer, 11)

    assert controller.writes == [("output", 1001, True), ("output", 1004, True)]
    assert len(events) == 1
    assert events[0].data == {
        "entry_id": config_entry.entry_id,
        "site_id": SITE_ID,
        "module_ids": [MODULE],
        "device_ids": [1001, 1004],
        "failed_device_ids": [],
        "restored": 2,
        "failed": 0,
    }
    assert len(notifications) == 1
    assert notifications[0]["title"] == "Power cut: restored 2 outputs"
    assert "- Kitchen light\n- Pump relay" in notifications[0]["message"]
    assert "Hall dimmer" not in notifications[0]["message"]
    state = hass.states.get(_power_loss_sensor(hass))
    assert state is not None
    assert dt_util.parse_datetime(state.state) == lost_at.replace(microsecond=0)


async def test_driver_report_during_grace_does_not_overwrite_memory(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    manager = await _setup(hass, controller, config_entry, [1001])
    await _push(controller, MODULE, online=False)
    await _push(controller, MODULE, online=True)
    await _advance(hass, freezer, 5)
    await _push(controller, 1001, output=False)
    await _advance(hass, freezer, 100)
    assert manager.memory["1001"] == {"on": True}
    assert controller.writes == [("output", 1001, True)]
    await _advance(hass, freezer, 20)
    assert manager.memory["1001"] == {"on": False}
    await _push(controller, 1001, output=True)
    assert manager.memory["1001"] == {"on": True}


async def test_matching_outputs_are_not_written(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    notifications: list[dict[str, Any]],
) -> None:
    events = async_capture_events(hass, EVENT_OUTPUTS_RESTORED)
    await _setup(hass, controller, config_entry, [1003])
    await _push(controller, MODULE, online=False)
    await _push(controller, 1003, output=False)
    await _push(controller, MODULE, online=True)
    await _push(controller, 1003, output=True)
    await _advance(hass, freezer, 11)
    assert controller.writes == []
    assert events == []
    assert notifications == []


async def test_startup_after_uptime_reset_restores(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    _prepare(controller)
    _stored(
        config_entry,
        hass_storage,
        {
            "outputs": {"1001": {"on": True}, "1004": {"on": False}},
            "modules": {str(MODULE): {"uptime": 5000, "seen": "2026-10-01T10:00:00+00:00"}},
            "last_power_loss": None,
        },
    )
    _status(controller, MODULE)["uptime"] = 30
    for device_id in (1001, 1004):
        _status(controller, device_id)["output"] = False
    manager = await _start(hass, controller, config_entry, [1001, 1004])
    assert manager.memory["1001"] == {"on": True}
    assert manager.last_power_loss == dt_util.utcnow()
    await _advance(hass, freezer, 11)
    assert controller.writes == [("output", 1001, True)]


async def test_ha_restart_without_uptime_reset_restores_nothing(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    _prepare(controller)
    _stored(
        config_entry,
        hass_storage,
        {
            "outputs": {"1001": {"on": True}},
            "modules": {str(MODULE): {"uptime": 4000, "seen": "2026-10-01T10:00:00+00:00"}},
            "last_power_loss": None,
        },
    )
    _status(controller, 1001)["output"] = False
    manager = await _start(hass, controller, config_entry, [1001])
    await _advance(hass, freezer, 200)
    assert controller.writes == []
    assert manager.last_power_loss is None
    assert manager.memory["1001"] == {"on": False}
    assert manager.module_state[str(MODULE)]["uptime"] == 5000


async def test_network_drop_restores_nothing(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    manager = await _setup(hass, controller, config_entry, [1001])
    hub = config_entry.runtime_data
    _status(controller, MODULE)["uptime"] = 5600
    _status(controller, 1001)["output"] = False
    await controller.push(AgatarkError("stream lost"))
    await hass.async_block_till_done()
    assert hub.connected
    await _advance(hass, freezer, 200)
    assert controller.writes == []
    assert manager.last_power_loss is None


async def test_module_rebooted_during_network_drop_restores(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    manager = await _setup(hass, controller, config_entry, [1001])
    _status(controller, MODULE)["uptime"] = 40
    _status(controller, 1001)["output"] = False
    await controller.push(AgatarkError("stream lost"))
    await hass.async_block_till_done()
    assert manager.memory["1001"] == {"on": True}
    await _advance(hass, freezer, 11)
    assert controller.writes == [("output", 1001, True)]


async def test_dimmer_level_is_restored(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    manager = await _setup(hass, controller, config_entry, [DIMMER])
    assert manager.memory[str(DIMMER)] == {"on": True, "level": 60}
    await _push(controller, DIMMER_MODULE, online=False)
    await _push(controller, DIMMER, on=False, target=0, level=0)
    await _push(controller, DIMMER_MODULE, online=True)
    await _advance(hass, freezer, 11)
    assert controller.writes == [("devices", DIMMER, {"status": {"on": True, "target": 60}})]


async def test_writes_are_paced(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, controller, config_entry, [1001, 1003, 1004])
    await _push(controller, MODULE, online=False)
    await _all_off(controller)
    await _push(controller, MODULE, online=True)
    sleep = asyncio.sleep

    async def pause(delay: float, *args: Any) -> Any:
        if delay == 0.3:
            controller.writes.append(("pause", 0, delay))
        return await sleep(0, *args)

    with (
        patch("custom_components.sabatark.restore.WRITE_INTERVAL", 0.3),
        patch("custom_components.sabatark.restore.asyncio.sleep", pause),
    ):
        await _advance(hass, freezer, 11)
    assert controller.writes == [
        ("output", 1001, True),
        ("pause", 0, 0.3),
        ("output", 1003, True),
        ("pause", 0, 0.3),
        ("output", 1004, True),
    ]


async def test_failed_write_is_retried_once_and_reported(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    notifications: list[dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    events = async_capture_events(hass, EVENT_OUTPUTS_RESTORED)
    await _setup(hass, controller, config_entry, [1001, 1004])
    await _push(controller, MODULE, online=False)
    await _all_off(controller)
    await _push(controller, MODULE, online=True)
    client = controller.clients[-1]
    attempts: list[int] = []
    original = client.set_output

    async def flaky(device_id: int, on: bool) -> None:
        attempts.append(device_id)
        if device_id == 1004 or attempts.count(device_id) == 1:
            raise AgatarkError(f"rejected by {HOST}")
        await original(device_id, on)

    client.set_output = flaky
    with caplog.at_level(logging.INFO):
        await _advance(hass, freezer, 11)
    assert attempts == [1001, 1001, 1004, 1004]
    assert controller.writes == [("output", 1001, True)]
    assert events[0].data["device_ids"] == [1001]
    assert events[0].data["failed_device_ids"] == [1004]
    assert "Could not restore output 1004 (AgatarkError)" in caplog.text
    assert HOST not in caplog.text
    assert "could not be restored:\n- Pump relay" in notifications[0]["message"]


async def test_estonian_notification(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    notifications: list[dict[str, Any]],
) -> None:
    hass.config.language = "et"
    await _setup(hass, controller, config_entry, [1001])
    await _push(controller, MODULE, online=False)
    await _push(controller, 1001, output=False)
    await _push(controller, MODULE, online=True)
    await _advance(hass, freezer, 11)
    assert notifications[0]["title"] == "Voolukatkestus: taastati 1 väljundit"
    assert "- Kitchen light" in notifications[0]["message"]


async def test_store_round_trip(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    manager = await _setup(hass, controller, config_entry, [1001, DIMMER])
    await _push(controller, MODULE, online=False)
    lost_at = manager.last_power_loss
    assert lost_at is not None
    await _push(controller, 1001, output=False)
    await _push(controller, MODULE, online=True, uptime=7)
    await _advance(hass, freezer, 11)
    await hass.config_entries.async_unload(config_entry.entry_id)
    data = hass_storage[_store_key(config_entry)]["data"]
    assert data["outputs"] == {"1001": {"on": True}, str(DIMMER): {"on": True, "level": 60}}
    assert data["modules"][str(MODULE)]["uptime"] == 7
    assert data["last_power_loss"] == lost_at.isoformat()
    assert data["last_restore"]["restored"] == [1001]

    _status(controller, MODULE)["uptime"] = 9
    _status(controller, 1001)["output"] = True
    writes = list(controller.writes)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    reloaded = config_entry.runtime_data.restore
    assert reloaded.memory == manager.memory
    assert reloaded.last_power_loss == lost_at
    assert reloaded.module_state[str(MODULE)]["uptime"] == 9
    await _advance(hass, freezer, 200)
    assert controller.writes == writes
    state = hass.states.get(_power_loss_sensor(hass))
    assert dt_util.parse_datetime(state.state) == lost_at.replace(microsecond=0)


async def test_debounced_save(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    await _setup(hass, controller, config_entry, [1001])
    await _push(controller, 1001, output=False)
    await _advance(hass, freezer, 6)
    assert hass_storage[_store_key(config_entry)]["data"]["outputs"] == {"1001": {"on": False}}


async def test_options_offer_only_restorable_outputs(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    _prepare(controller)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "restore"}
    )
    assert result["step_id"] == "restore"
    schema = {str(key): key for key in result["data_schema"].schema}
    offered = result["data_schema"].schema[schema["devices"]].config["options"]
    assert sorted(item["value"] for item in offered) == ["1001", "1002", "1003", "1004", "1101"]
    assert schema["devices"].default() == []
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"policy": "last_state", "devices": ["1004", "1001"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert config_entry.options["restore"] == {"policy": "last_state", "devices": [1001, 1004]}
    assert config_entry.runtime_data.restore.selected == [1001, 1004]


async def test_access_devices_are_never_restored(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    manager = await _setup(hass, controller, config_entry, [1001, 1010])
    assert manager.selected == [1001]
    assert "1010" not in manager.memory


async def test_diagnostics_include_restore_state(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, controller, config_entry, [1001])
    report = await async_get_config_entry_diagnostics(hass, config_entry)
    restore = report["hub"]["restore"]
    assert restore["policy"] == "last_state"
    assert restore["selected"] == [1001]
    assert restore["remembered"] == {"1001": {"on": True}}
    assert restore["modules"][str(MODULE)]["online"] is True
    assert restore["modules"][str(MODULE)]["uptime"] == 5000
    assert "Kitchen light" not in json.dumps(restore)


async def test_startup_during_outage_restores_when_module_returns(
    hass: HomeAssistant,
    controller: FakeController,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
) -> None:
    _prepare(controller)
    _stored(
        config_entry,
        hass_storage,
        {
            "outputs": {"1001": {"on": True}},
            "modules": {str(MODULE): {"uptime": 5000, "seen": "2026-10-01T10:00:00+00:00"}},
            "last_power_loss": "2026-09-01T10:00:00+00:00",
        },
    )
    _status(controller, MODULE)["online"] = False
    _status(controller, 1001)["output"] = False
    manager = await _start(hass, controller, config_entry, [1001])
    assert manager.last_power_loss == dt_util.utcnow()
    assert manager.memory["1001"] == {"on": True}
    await _advance(hass, freezer, 1200)
    assert controller.writes == []
    await _push(controller, MODULE, online=True, uptime=3)
    await _advance(hass, freezer, 11)
    assert controller.writes == [("output", 1001, True)]
