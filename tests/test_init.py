"""Tests for setup, session persistence, the event stream and unload."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sabatark import (
    AgatarkError,
    AuthError,
    EventLog,
    EventOp,
    SessionState,
    UplinkError,
    parse_event,
)

from custom_components.sabatark.const import CONF_SESSION, DOMAIN

from .conftest import HOST, OTHER_SITE_ID, SITE_ID, FakeController, entity_id


async def test_setup_restores_session_without_login(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    assert loaded_entry.state is ConfigEntryState.LOADED
    client = controller.clients[0]
    assert client.restored is not None
    assert client.restored.authorization == "session-stored"
    assert controller.logins == 0
    assert controller.streams == 1


async def test_new_session_is_saved_in_entry(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    client = controller.clients[0]
    client.on_session_change(
        SessionState(authorization="session-new", user_id=41, base_url=HOST, email="x@example.com")
    )
    assert loaded_entry.data[CONF_SESSION]["authorization"] == "session-new"
    client.on_session_change(None)
    assert CONF_SESSION not in loaded_entry.data


async def test_invalid_stored_session_is_ignored(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_SESSION: {"authorization": 5}}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert controller.clients[0].restored is None
    assert controller.logins == 1
    assert config_entry.data[CONF_SESSION]["authorization"] == "session-1"


async def test_setup_auth_failure_starts_reauth(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    controller.read_error = AuthError("expired", status=401)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]
    assert controller.clients[0].closed is True


async def test_setup_connection_failure_retries(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    controller.read_error = AgatarkError("HTTP 503", status=503)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert controller.clients[0].closed is True


async def test_setup_missing_site_fails(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    controller.sites = [{"id": OTHER_SITE_ID, "name": "Cabin"}]
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_unload_closes_client_without_logout(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED
    client = controller.clients[0]
    assert client.closed is True
    assert client.logout_on_close is False


async def test_devices_are_registered_under_site_hub(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    registry = dr.async_get(hass)
    hub = registry.async_get_device_by_identifier((DOMAIN, str(SITE_ID)), loaded_entry.entry_id)
    assert hub is not None
    assert hub.name == "Home"
    light = registry.async_get_device_by_identifier(
        (DOMAIN, f"{SITE_ID}_1001"), loaded_entry.entry_id
    )
    assert light is not None
    assert light.name == "Kitchen light"
    assert light.via_device_id == hub.id
    assert light.model == "light"
    access = registry.async_get_device_by_identifier(
        (DOMAIN, f"{SITE_ID}_1010"), loaded_entry.entry_id
    )
    assert access is not None
    assert access.model == "access"
    assert access.via_device_id == hub.id
    for skipped in (1011, 1014, 2001):
        assert (
            registry.async_get_device_by_identifier(
                (DOMAIN, f"{SITE_ID}_{skipped}"), loaded_entry.entry_id
            )
            is None
        )


async def test_suggested_area_from_room(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{SITE_ID}_1005"), loaded_entry.entry_id
    )
    assert device is not None
    assert device.area_id == "hall"


async def test_deltas_update_state_in_order(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    target = entity_id(hass, "light", 1001, "light")
    await hass.async_block_till_done()
    assert hass.states.get(target).state == STATE_OFF
    seen: list[str] = []
    hass.bus.async_listen(
        "state_changed",
        lambda event: (
            seen.append(event.data["new_state"].state)
            if event.data["entity_id"] == target
            and event.data["old_state"].state != event.data["new_state"].state
            else None
        ),
    )
    await controller.push(
        parse_event({"id": 1001, "status": {"output": True}}),
        parse_event({"id": 1001, "status": {"output": False}}),
        parse_event({"id": 1001, "status": {"output": True}}),
        parse_event({"id": 9999, "status": {"output": True}}),
        parse_event({"op": "api.reload"}),
    )
    await hass.async_block_till_done()
    assert seen == [STATE_ON, STATE_OFF, STATE_ON]
    assert hass.states.get(target).state == STATE_ON


async def test_gesture_listeners(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    hub = loaded_entry.runtime_data
    received: list[EventLog] = []
    unsubscribe = hub.async_subscribe_gestures(1005, received.append)
    hub.async_subscribe_gestures(1006, lambda event: 1 / 0)
    gesture = {
        "op": "log",
        "id": 1005,
        "time": 1_700_000_000_000,
        "key": "singleClick:/status/input",
    }
    await controller.push(
        parse_event(gesture),
        parse_event({**gesture, "id": 1006}),
        parse_event({**gesture, "key": "doubleClick:/status/input"}),
    )
    assert [event.gesture for event in received] == ["singleClick", "doubleClick"]
    unsubscribe()
    await controller.push(parse_event(gesture))
    assert len(received) == 2


async def test_device_offline_makes_entities_unavailable(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    assert hass.states.get(entity_id(hass, "light", 1012, "light")).state == STATE_UNAVAILABLE
    await controller.push(parse_event({"id": 1001, "status": {"online": False}}))
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "light", 1001, "light")).state == STATE_UNAVAILABLE
    await controller.push(parse_event({"id": 1001, "status": {"online": True}}))
    await hass.async_block_till_done()
    assert hass.states.get(entity_id(hass, "light", 1001, "light")).state == STATE_OFF


async def test_stream_error_marks_unavailable_and_resyncs(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    hub = loaded_entry.runtime_data
    controller.read_error = AgatarkError("HTTP 504", status=504)
    await controller.push(UplinkError("HTTP 504", status=504))
    await hass.async_block_till_done()
    assert not hub.connected
    assert hass.states.get(entity_id(hass, "light", 1001, "light")).state == STATE_UNAVAILABLE

    controller.read_error = None
    controller.devices[0]["status"]["output"] = True
    await controller.push(EventOp(op=""))
    for _ in range(20):
        if hub.connected:
            break
        await controller.push()
    await hass.async_block_till_done()
    assert hub.connected
    assert hass.states.get(entity_id(hass, "light", 1001, "light")).state == STATE_ON
    assert controller.streams >= 2


async def test_stream_auth_error_starts_reauth(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    await controller.push(AuthError("expired", status=401))
    await hass.async_block_till_done()
    assert not loaded_entry.runtime_data.connected
    assert hass.states.get(entity_id(hass, "switch", 1004, "switch")).state == STATE_UNAVAILABLE
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_unique_ids(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    registry = er.async_get(hass)
    assert (
        registry.async_get(entity_id(hass, "light", 1001, "light")).unique_id
        == f"{SITE_ID}_1001_light"
    )
    assert (
        registry.async_get(entity_id(hass, "switch", 1004, "switch")).unique_id
        == f"{SITE_ID}_1004_switch"
    )
