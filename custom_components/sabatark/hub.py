"""Runtime hub: one controller session, the site's devices and the event stream."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from typing import TYPE_CHECKING, Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later

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

from .const import DOMAIN, MANUFACTURER, RECONNECT_INITIAL, RECONNECT_MAX, UNAVAILABLE_GRACE
from .controls import Controls, parse_controls

if TYPE_CHECKING:
    from .restore import RestoreManager

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


def _conf_inputs(device: Device) -> set[tuple[Any, Any]]:
    return {
        (item.get("id"), item.get("path"))
        for item in device.conf
        if item.get("mode") == "input" and item.get("id") is not None and item.get("path")
    }


def duplicate_detectors(devices: Iterable[Device]) -> set[int]:
    """Return status-less detectors whose every input is already an access device's input."""
    devices = list(devices)
    access_inputs = set().union(
        *(_conf_inputs(device) for device in devices if device.type == "access")
    )
    duplicates = set()
    for device in devices:
        if device.type != "securityDetector" or device.raw.get("status") or not device.conf:
            continue
        if all((item.get("id"), item.get("path")) in access_inputs for item in device.conf):
            duplicates.add(device.id)
    return duplicates


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
        logical = [device for device in devices if device.site_id == site.id and is_logical(device)]
        duplicates = duplicate_detectors(logical)
        for device_id in sorted(duplicates):
            _LOGGER.debug("Skipping detector %s that duplicates an access device input", device_id)
        self.devices: dict[int, Device] = {
            device.id: device for device in logical if device.id not in duplicates
        }
        self.rooms: dict[int, Room] = {room.id: room for room in rooms if room.site_id == site.id}
        self.templates: dict[int, Device] = {device.id: device for device in devices}
        self._stream_ok = True
        self._reachable = client.connected is not False
        self._available = self._stream_ok and self._reachable
        self._grace: CALLBACK_TYPE | None = None
        self.hub_device_id: str | None = None
        self._device_listeners: dict[int, list[DeviceListener]] = {}
        self._gesture_listeners: dict[int, list[GestureListener]] = {}
        self._task: asyncio.Task[None] | None = None
        self.restore: RestoreManager | None = None

    @property
    def connected(self) -> bool:
        """Return whether entities are available, allowing a grace period after connection loss."""
        return self._available

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

    def provides(self, device_entry: dr.DeviceEntry) -> bool:
        """Return whether a registry device is the site hub or a device the hub provides."""
        provided = {self.hub_identifier} | {
            self.device_identifier(device_id) for device_id in self.devices
        }
        return any(
            domain == DOMAIN and identifier in provided
            for domain, identifier in device_entry.identifiers
        )

    @callback
    def async_remove_stale_devices(self) -> None:
        """Remove registry devices of this entry that the hub no longer provides."""
        registry = dr.async_get(self.hass)
        for device_entry in dr.async_entries_for_config_entry(registry, self.entry.entry_id):
            if self.provides(device_entry):
                continue
            _LOGGER.debug("Removing stale device %s", device_entry.id)
            registry.async_update_device(
                device_entry.id, remove_config_entry_id=self.entry.entry_id
            )

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
    def async_handle_connection_change(self, connected: bool) -> None:
        """Track controller reachability reported by the client."""
        if self._reachable == connected:
            return
        self._set_flags(reachable=connected)

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
        self._cancel_grace()
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
            device = self.devices.get(event.id) or self.templates.get(event.id)
            if device is None:
                return
            updated = device.apply(event)
            self.templates[event.id] = updated
            if event.id in self.devices:
                self.devices[event.id] = updated
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
                self._stream_ok = False
                self._cancel_grace()
                self._set_available(False)
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
        self._set_flags(stream_ok=True)
        for device_id in list(self._device_listeners):
            self._notify_device(device_id)

    @callback
    def _async_set_connected(self, connected: bool) -> None:
        self._set_flags(stream_ok=connected)

    def _set_flags(self, *, stream_ok: bool | None = None, reachable: bool | None = None) -> None:
        if stream_ok is not None:
            self._stream_ok = stream_ok
        if reachable is not None:
            self._reachable = reachable
        if self._stream_ok and self._reachable:
            self._cancel_grace()
            if not self._available:
                _LOGGER.info("Connection to the controller restored")
                self._set_available(True)
        elif self._available and self._grace is None:
            _LOGGER.debug(
                "Controller unreachable; entities stay available for %.0f s", UNAVAILABLE_GRACE
            )
            self._grace = async_call_later(self.hass, UNAVAILABLE_GRACE, self._async_grace_expired)

    @callback
    def _async_grace_expired(self, _now: Any) -> None:
        self._grace = None
        if self._stream_ok and self._reachable:
            return
        _LOGGER.warning("Lost connection to the controller")
        self._set_available(False)

    def _cancel_grace(self) -> None:
        if self._grace is not None:
            self._grace()
            self._grace = None

    def _set_available(self, available: bool) -> None:
        self._available = available
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
