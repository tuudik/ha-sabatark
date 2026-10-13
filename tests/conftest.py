"""Fixtures: a fake controller behind a fake AgatarkClient built on the real sabatark models."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Generator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import PropertyMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sabatark import (
    AuthError,
    Device,
    Event,
    Hello,
    Room,
    SessionState,
    Site,
    derive_token,
)

from custom_components.sabatark.const import (
    CONF_SESSION,
    CONF_SITE_ID,
    CONF_TOKEN,
    CONF_USER_ID,
    DOMAIN,
)

HOST = "http://192.0.2.10"
EMAIL = "owner@example.com"
PASSWORD = "correct horse"
USER_ID = 41
SITE_ID = 10
OTHER_SITE_ID = 20

SITES = [{"id": SITE_ID, "name": "Home"}, {"id": OTHER_SITE_ID, "name": "Cabin"}]
ROOMS = [
    {"id": 100, "name": "Kitchen", "siteId": SITE_ID},
    {"id": 101, "name": "Hall", "siteId": SITE_ID},
    {"id": 200, "name": "Cabin room", "siteId": OTHER_SITE_ID},
]


def _device(
    device_id: int,
    name: str,
    type_: str,
    usage: dict[str, list[str]] | None,
    status: dict[str, Any],
    room_id: int = 100,
    site_id: int = SITE_ID,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": device_id,
        "name": name,
        "type": type_,
        "enabled": True,
        "roomId": room_id,
        "siteId": site_id,
        "usage": usage,
        "status": status,
        **extra,
    }


def device_data() -> list[dict[str, Any]]:
    """Return a synthetic device list covering every mapped kind of device."""
    return [
        _device(
            1001,
            "Kitchen light",
            "light",
            {"light": ["indoorIndividual"]},
            {"online": True, "output": False},
        ),
        _device(
            1002,
            "Hall dimmer",
            "outputPwm",
            {},
            {"online": True, "output": True, "level": 40, "fadeTime": 2},
            room_id=101,
        ),
        _device(
            1003,
            "Garden light",
            "",
            {"light": ["outdoor"]},
            {"online": True, "output": False, "scheduleOn": True},
        ),
        _device(
            1004, "Pump relay", "output", {"output": ["generic"]}, {"online": True, "output": False}
        ),
        _device(
            1005,
            "Hall switch",
            "switch",
            {"switch": ["generic"]},
            {"online": True, "input": False},
            room_id=101,
        ),
        _device(
            1006,
            "Hall motion",
            "securityDetector",
            {"securityDetector": ["motion"]},
            {"online": True, "active": False},
            room_id=101,
        ),
        _device(
            1007,
            "Front door",
            "securityDetector",
            {"securityDetector": ["perimeter", "door"]},
            {"online": True, "open": False},
            room_id=101,
        ),
        _device(
            1008,
            "Kitchen smoke",
            "securityDetector24",
            {"securityDetector24": ["fire"]},
            {"online": True, "active": False},
        ),
        _device(
            1009,
            "Kitchen climate",
            "climateSensor",
            {"climateSensor": ["airTemperature"]},
            {
                "online": True,
                "temperature": 21.5,
                "rh": 40.0,
                "co2": 600,
                "lux": 120,
                "ventilationNeed": 3,
            },
        ),
        _device(
            1010,
            "Front door lock",
            "access",
            {"access": ["lock"]},
            {"online": True, "locked": True, "open": False},
            room_id=101,
        ),
        _device(
            1011,
            "IO module",
            "ioModule_Modbus",
            None,
            {"online": True, "voltage": 24.1},
            parentId=1099,
        ),
        _device(1012, "Porch light", "light", {"light": [""]}, {"online": False, "output": False}),
        _device(
            1013,
            "Breaker check",
            "input",
            {"input": ["circuitBreakerCheck"]},
            {"online": True, "active": False},
        ),
        _device(
            1014,
            "Main controller",
            "smartController",
            {"controller": ["smart"]},
            {"online": True, "voltage": 12.0},
        ),
        _device(
            2001,
            "Cabin light",
            "light",
            {"light": [""]},
            {"online": True, "output": False},
            room_id=200,
            site_id=OTHER_SITE_ID,
        ),
    ]


@dataclass
class FakeController:
    """State and call log shared by every FakeClient instance."""

    sites: list[dict[str, Any]] = field(default_factory=lambda: list(SITES))
    devices: list[dict[str, Any]] = field(default_factory=device_data)
    rooms: list[dict[str, Any]] = field(default_factory=lambda: list(ROOMS))
    user_id: int = USER_ID
    token: str = field(default_factory=lambda: derive_token(PASSWORD, EMAIL))
    login_error: BaseException | None = None
    read_error: BaseException | None = None
    write_error: BaseException | None = None
    clients: list[FakeClient] = field(default_factory=list)
    logins: int = 0
    writes: list[tuple[str, int, Any]] = field(default_factory=list)
    queue: asyncio.Queue[Event | BaseException] = field(default_factory=asyncio.Queue)
    streams: int = 0

    async def push(self, *items: Event | BaseException) -> None:
        """Feed items to the event stream and wait until they are consumed."""
        for item in items:
            self.queue.put_nowait(item)
        for _ in range(200):
            if self.queue.empty():
                break
            await asyncio.sleep(0)
        await asyncio.sleep(0)


class FakeClient:
    """Stand-in for sabatark.AgatarkClient that talks to a FakeController."""

    controller: FakeController

    def __init__(
        self,
        base_url: str,
        email: str | None = None,
        password: str | None = None,
        token: str | None = None,
        session: Any = None,
        guard: Any = None,
        *,
        session_state: SessionState | None = None,
        on_session_change: Any = None,
        **kwargs: Any,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.token = token
        self.restored = session_state
        self.on_session_change = on_session_change
        self._state = session_state
        self.closed: bool | None = None
        self.logout_on_close: bool | None = None
        self.controller.clients.append(self)

    @property
    def session_state(self) -> SessionState | None:
        return self._state

    async def login(self) -> Hello:
        controller = self.controller
        if controller.login_error is not None:
            raise controller.login_error
        if self.token != controller.token:
            raise AuthError("Login rejected", status=401)
        controller.logins += 1
        self._state = SessionState(
            authorization=f"session-{controller.logins}",
            user_id=controller.user_id,
            base_url=self.base_url,
            email=(self.email or "").lower(),
        )
        if self.on_session_change is not None:
            self.on_session_change(self._state)
        return Hello(authorization=self._state.authorization, user={"id": controller.user_id})

    async def _read(self) -> None:
        if self.controller.read_error is not None:
            raise self.controller.read_error
        if self._state is None:
            await self.login()

    async def sites(self) -> list[Site]:
        await self._read()
        return [Site.from_dict(item) for item in self.controller.sites]

    async def devices(self) -> list[Device]:
        await self._read()
        return [Device.from_dict(item) for item in self.controller.devices]

    async def rooms(self) -> list[Room]:
        await self._read()
        return [Room.from_dict(item) for item in self.controller.rooms]

    async def set_output(self, device_id: int, on: bool) -> None:
        if self.controller.write_error is not None:
            raise self.controller.write_error
        self.controller.writes.append(("output", device_id, on))

    async def patch(self, collection: str, id: int, data: Any, confirm: str | None = None) -> None:
        if self.controller.write_error is not None:
            raise self.controller.write_error
        self.controller.writes.append((collection, id, data))

    async def events(self, **kwargs: Any) -> AsyncIterator[Event]:
        self.controller.streams += 1
        while True:
            item = await self.controller.queue.get()
            if isinstance(item, BaseException):
                raise item
            yield item

    async def close(self, logout: bool = False) -> None:
        self.closed = True
        self.logout_on_close = logout


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components in every test."""


@pytest.fixture
def controller() -> Generator[FakeController]:
    """Patch AgatarkClient with a fake bound to a fresh controller."""
    fake = FakeController()
    client_class = type("BoundFakeClient", (FakeClient,), {"controller": fake})
    with (
        patch("custom_components.sabatark.AgatarkClient", client_class),
        patch("custom_components.sabatark.config_flow.AgatarkClient", client_class),
        patch("custom_components.sabatark.hub.RECONNECT_INITIAL", 0),
    ):
        yield fake


def stored_session() -> dict[str, Any]:
    """Return a stored session as the config flow persists it."""
    return SessionState(
        authorization="session-stored", user_id=USER_ID, base_url=HOST, email=EMAIL
    ).to_dict()


@pytest.fixture
async def config_entry(hass: HomeAssistant) -> AsyncIterator[MockConfigEntry]:
    """Return a config entry for the Home site, unloaded after the test."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id=f"{USER_ID}_{SITE_ID}",
        data={
            CONF_HOST: HOST,
            CONF_EMAIL: EMAIL,
            CONF_TOKEN: derive_token(PASSWORD, EMAIL),
            CONF_USER_ID: USER_ID,
            CONF_SITE_ID: SITE_ID,
            CONF_SESSION: stored_session(),
        },
    )
    entry.add_to_hass(hass)
    yield entry
    await hass.async_block_till_done()
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)


@pytest.fixture
async def loaded_entry(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set up the integration."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
def enable_all_entities() -> Generator[None]:
    """Create entities that are disabled by default as enabled."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        return_value=True,
        new_callable=PropertyMock,
    ):
        yield


def entity_id(hass: HomeAssistant, platform: str, device_id: int, key: str) -> str:
    """Return the entity id registered for one key of a controller device."""
    found = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{SITE_ID}_{device_id}_{key}")
    assert found is not None, (platform, device_id, key)
    return found
