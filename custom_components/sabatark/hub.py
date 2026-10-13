"""Runtime hub: one controller session, the site's devices and the event stream."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from contextlib import suppress
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo

from sabatark import (
    AgatarkClient,
    AgatarkError,
    AuthError,
    Device,
    Event,
    EventDelta,
    EventLog,
    Room,
    Site,
)

from .const import DOMAIN, MANUFACTURER, RECONNECT_INITIAL, RECONNECT_MAX
from .controls import Controls, parse_controls

_LOGGER = logging.getLogger(__name__)

type SabatarkConfigEntry = ConfigEntry[SabatarkHub]
type DeviceListener = Callable[[], None]
type GestureListener = Callable[[EventLog], None]


def is_logical(device: Device) -> bool:
    """Return whether a device is a logical device rather than a hardware module or driver."""
    raw_usage = device.raw.get("usage")
    return (
        "parentId" not in device.raw and raw_usage is not None and "controller" not in device.usage
    )


class SabatarkHub:
    """Owns the controller client, the device map of one site and the listener registry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SabatarkConfigEntry,
        client: AgatarkClient,
        site: Site,
        devices: list[Device],
        rooms: list[Room],
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.site = site
        self.site_id = site.id
        self.devices: dict[int, Device] = {
            device.id: device
            for device in devices
            if device.site_id == site.id and is_logical(device)
        }
        self.rooms: dict[int, Room] = {room.id: room for room in rooms if room.site_id == site.id}
        self.templates: dict[int, Device] = {device.id: device for device in devices}
        self.connected = True
        self.hub_device_id: str | None = None
        self._device_listeners: dict[int, list[DeviceListener]] = {}
        self._gesture_listeners: dict[int, list[GestureListener]] = {}
        self._task: asyncio.Task[None] | None = None

    @property
    def hub_identifier(self) -> str:
        return str(self.site_id)

    def device_identifier(self, device_id: int) -> str:
        """Return the device registry identifier of a controller device."""
        return f"{self.site_id}_{device_id}"

    def unique_id(self, device_id: int, key: str) -> str:
        """Return the entity unique id for one key of a controller device."""
        return f"{self.site_id}_{device_id}_{key}"

    def device_info(self, device: Device) -> DeviceInfo:
        """Return the registry entry of a controller device, attached to the site hub."""
        room = self.rooms.get(device.room_id) if device.room_id is not None else None
        info = DeviceInfo(
            identifiers={(DOMAIN, self.device_identifier(device.id))},
            name=device.name or f"{device.type or 'device'} {device.id}",
            manufacturer=MANUFACTURER,
            model=device.type or None,
            suggested_area=room.name if room else None,
        )
        if self.hub_device_id is not None:
            info["via_device_id"] = self.hub_device_id
        return info

    @callback
    def async_register_hub_device(self) -> None:
        """Register the site as the hub device that controller devices are attached to."""
        hub_device = dr.async_get(self.hass).async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, self.hub_identifier)},
            name=self.site.name or self.entry.title,
            manufacturer=MANUFACTURER,
            model="Agatark controller",
            configuration_url=self.client.base_url,
        )
        self.hub_device_id = hub_device.id

    def is_available(self, device_id: int) -> bool:
        """Return whether the hub is connected and the device does not report itself offline."""
        device = self.devices.get(device_id)
        return self.connected and device is not None and device.status.get("online") is not False

    def controls(self, device_id: int) -> Controls:
        """Return the controls declared in a device's ui."""
        device = self.devices.get(device_id) or self.templates.get(device_id)
        if device is None:
            return Controls()
        return parse_controls(device, self.templates)

    @callback
    def async_subscribe_device(self, device_id: int, listener: DeviceListener) -> CALLBACK_TYPE:
        """Call listener after each status change of a device and on hub connectivity changes."""
        return self._subscribe(self._device_listeners, device_id, listener)

    @callback
    def async_subscribe_gestures(self, device_id: int, listener: GestureListener) -> CALLBACK_TYPE:
        """Call listener with every gesture log item of a device."""
        return self._subscribe(self._gesture_listeners, device_id, listener)

    async def async_set_output(self, device_id: int, on: bool) -> None:
        """Switch an output on or off."""
        await self._write(self.client.set_output(device_id, on))

    async def async_patch_status(self, device_id: int, status: Mapping[str, Any]) -> None:
        """Merge-patch status fields of a device."""
        await self._write(self.client.patch("devices", device_id, {"status": dict(status)}))

    @callback
    def async_start(self) -> None:
        """Start consuming the event stream in the background."""
        self._task = self.entry.async_create_background_task(
            self.hass, self._async_run(), f"{DOMAIN} events {self.site_id}"
        )

    async def async_stop(self, *_: Any) -> None:
        """Stop the event stream and close the client without logging out."""
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.client.close()

    @callback
    def async_handle_event(self, event: Event) -> None:
        """Apply one event stream item and notify its listeners."""
        if isinstance(event, EventDelta):
            device = self.devices.get(event.id)
            if device is None:
                return
            self.devices[event.id] = device.apply(event)
            self._notify_device(event.id)
        elif isinstance(event, EventLog):
            for listener in list(self._gesture_listeners.get(event.id, ())):
                self._call(listener, event)
        else:
            _LOGGER.debug("Ignoring event %s", event)

    async def _async_run(self) -> None:
        delay = RECONNECT_INITIAL
        resync = False
        while True:
            try:
                if resync:
                    self._async_refresh(await self.client.devices())
                    resync = False
                    delay = RECONNECT_INITIAL
                async for event in self.client.events():
                    self.async_handle_event(event)
            except AuthError:
                _LOGGER.warning("Controller rejected the session; reauthentication required")
                self._async_set_connected(False)
                self.entry.async_start_reauth(self.hass)
                return
            except (AgatarkError, aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.warning("Event stream failed (%s); retrying in %.0f s", err, delay)
                self._async_set_connected(False)
            resync = True
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX)

    @callback
    def _async_refresh(self, devices: list[Device]) -> None:
        for device in devices:
            self.templates[device.id] = device
            if device.id in self.devices:
                self.devices[device.id] = device
        self.connected = True
        for device_id in list(self._device_listeners):
            self._notify_device(device_id)

    @callback
    def _async_set_connected(self, connected: bool) -> None:
        if self.connected == connected:
            return
        self.connected = connected
        for device_id in list(self._device_listeners):
            self._notify_device(device_id)

    def _notify_device(self, device_id: int) -> None:
        for listener in list(self._device_listeners.get(device_id, ())):
            self._call(listener)

    @staticmethod
    def _call(listener: Callable[..., None], *args: Any) -> None:
        try:
            listener(*args)
        except Exception:
            _LOGGER.exception("Error in listener")

    @staticmethod
    def _subscribe[T](registry: dict[int, list[T]], device_id: int, listener: T) -> CALLBACK_TYPE:
        registry.setdefault(device_id, []).append(listener)

        @callback
        def unsubscribe() -> None:
            listeners = registry.get(device_id, [])
            if listener in listeners:
                listeners.remove(listener)
            if not listeners:
                registry.pop(device_id, None)

        return unsubscribe

    async def _write(self, request: Any) -> None:
        try:
            await request
        except (AgatarkError, aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": str(err) or type(err).__name__},
            ) from err
