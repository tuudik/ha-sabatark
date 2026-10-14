"""Restore selected outputs after their I/O module loses power."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util

from sabatark import Device

from .const import DOMAIN
from .controls import DEFAULT_ONOFF, status_key
from .hub import SabatarkConfigEntry, SabatarkHub

_LOGGER = logging.getLogger(__name__)

CONF_RESTORE = "restore"
CONF_DEVICES = "devices"
CONF_POLICY = "policy"
POLICY_LAST_STATE = "last_state"

EVENT_OUTPUTS_RESTORED = f"{DOMAIN}_outputs_restored"
STORAGE_VERSION = 1
SAVE_DELAY = 5.0
SETTLE_DELAY = 10.0
GRACE_PERIOD = 120.0
WRITE_INTERVAL = 0.3

type Memory = dict[str, Any]
type Policy = Callable[[Memory | None], Memory | None]


def _last_state(memory: Memory | None) -> Memory | None:
    return dict(memory) if memory else None


POLICIES: dict[str, Policy] = {POLICY_LAST_STATE: _last_state}


def output_module(device: Device) -> int | None:
    """Return the id of the I/O module that drives an output device."""
    for item in device.conf:
        module_id = item.get("id")
        if item.get("mode") == "output" and isinstance(module_id, int):
            return module_id
    return None


def is_restorable(device: Device) -> bool:
    """Return whether an output can be restored: a light or switch on a known module."""
    return (
        device.is_output
        and device.type != "access"
        and "access" not in device.usage
        and output_module(device) is not None
    )


def restore_options(entry: SabatarkConfigEntry) -> dict[str, Any]:
    """Return the stored restore policy and selected device ids."""
    stored = entry.options.get(CONF_RESTORE, {})
    policy = stored.get(CONF_POLICY, POLICY_LAST_STATE)
    return {
        CONF_POLICY: policy if policy in POLICIES else POLICY_LAST_STATE,
        CONF_DEVICES: [int(device_id) for device_id in stored.get(CONF_DEVICES, [])],
    }


def restore_store(hass: HomeAssistant, entry: SabatarkConfigEntry) -> Store[dict[str, Any]]:
    """Return the store that holds an entry's restore memory."""
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.restore")


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


class RestoreManager:
    """Remembers selected outputs and restores them when their module returns from a power loss."""

    def __init__(self, hass: HomeAssistant, entry: SabatarkConfigEntry, hub: SabatarkHub) -> None:
        self.hass = hass
        self.entry = entry
        self.hub = hub
        options = restore_options(entry)
        self.policy: str = options[CONF_POLICY]
        restorable = {
            device.id: module_id
            for device in hub.devices.values()
            if is_restorable(device) and (module_id := output_module(device)) is not None
        }
        self.selected: list[int] = [
            device_id for device_id in options[CONF_DEVICES] if device_id in restorable
        ]
        self._module_of = {device_id: restorable[device_id] for device_id in self.selected}
        self.modules: list[int] = sorted(set(restorable.values()))
        self._store = restore_store(hass, entry)
        self.memory: dict[str, Memory] = {}
        self.module_state: dict[str, dict[str, Any]] = {}
        self.last_power_loss: datetime | None = None
        self.last_restore: dict[str, Any] | None = None
        self._online: dict[int, bool] = {}
        self._online_since: dict[int, datetime] = {}
        self._pending: set[int] = set()
        self._timers: dict[str, CALLBACK_TYPE] = {}
        self._unsubscribe: list[CALLBACK_TYPE] = []
        self._listeners: list[Callable[[], None]] = []

    async def async_start(self) -> None:
        """Load the stored memory, check modules for a reboot and follow device updates."""
        stored = await self._store.async_load() or {}
        self.memory = {
            key: dict(value)
            for key, value in stored.get("outputs", {}).items()
            if isinstance(value, Mapping)
        }
        self.module_state = {
            key: dict(value)
            for key, value in stored.get("modules", {}).items()
            if isinstance(value, Mapping)
        }
        self.last_power_loss = dt_util.parse_datetime(stored.get("last_power_loss") or "")
        self.last_restore = stored.get("last_restore")
        for module_id in self.modules:
            self._check_module(module_id)
            self._unsubscribe.append(
                self.hub.async_subscribe_device(module_id, self._module_listener(module_id))
            )
        for device_id in self.selected:
            self._record(device_id)
            self._unsubscribe.append(
                self.hub.async_subscribe_device(device_id, self._output_listener(device_id))
            )

    async def async_stop(self, *_: Any) -> None:
        """Stop following updates and write the memory to storage."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()
        await self._store.async_save(self._data())

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call listener when the last power loss changes."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def diagnostics(self) -> dict[str, Any]:
        """Return the feature state without names."""
        return {
            "policy": self.policy,
            "selected": self.selected,
            "modules": {
                str(module_id): {
                    "online": self._online.get(module_id),
                    **self.module_state.get(str(module_id), {}),
                }
                for module_id in self.modules
            },
            "remembered": self.memory,
            "pending": sorted(self._pending),
            "last_power_loss": self.last_power_loss.isoformat() if self.last_power_loss else None,
            "last_restore": self.last_restore,
        }

    def _module_listener(self, module_id: int) -> Callable[[], None]:
        @callback
        def changed() -> None:
            self._check_module(module_id)

        return changed

    def _output_listener(self, device_id: int) -> Callable[[], None]:
        @callback
        def changed() -> None:
            self._check_module(self._module_of[device_id])
            self._record(device_id)

        return changed

    def _module_status(self, module_id: int) -> dict[str, Any] | None:
        module = self.hub.templates.get(module_id)
        return module.status if module is not None else None

    def _check_module(self, module_id: int) -> None:
        status = self._module_status(module_id)
        if status is None or not self.hub.connected:
            return
        online = status.get("online") is not False
        was_online = self._online.get(module_id)
        self._online[module_id] = online
        key = str(module_id)
        stored = self.module_state.get(key, {})
        now = dt_util.utcnow()
        if not online:
            if was_online or (was_online is None and self._unseen_outage(stored)):
                self._power_lost(now)
            return
        uptime = status.get("uptime")
        rebooted = (
            _is_number(uptime) and _is_number(stored.get("uptime")) and uptime < stored["uptime"]
        )
        if rebooted and was_online is not False:
            self._power_lost(now)
        if was_online is False or rebooted:
            self._online_since[module_id] = now
            self._schedule_restore(module_id)
            self._schedule(
                f"grace_{module_id}", GRACE_PERIOD, lambda: self._record_module(module_id)
            )
        state = {"seen": now.isoformat()}
        if _is_number(uptime):
            state["uptime"] = uptime
        self.module_state[key] = state
        self._save()

    def _unseen_outage(self, stored: Mapping[str, Any]) -> bool:
        seen = dt_util.parse_datetime(stored.get("seen") or "")
        return self.last_power_loss is None or (seen is not None and seen > self.last_power_loss)

    def _power_lost(self, when: datetime) -> None:
        self.last_power_loss = when
        self._save()
        for listener in list(self._listeners):
            listener()

    def _recording(self, module_id: int) -> bool:
        if not self.hub.connected or not self._online.get(module_id):
            return False
        since = self._online_since.get(module_id)
        return since is None or dt_util.utcnow() - since >= timedelta(seconds=GRACE_PERIOD)

    def _record_module(self, module_id: int) -> None:
        for device_id, module in self._module_of.items():
            if module == module_id:
                self._record(device_id)

    def _record(self, device_id: int) -> None:
        if not self._recording(self._module_of[device_id]):
            return
        snapshot = self._snapshot(device_id)
        if snapshot is not None and snapshot != self.memory.get(str(device_id)):
            self.memory[str(device_id)] = snapshot
            self._save()

    def _keys(self, device_id: int) -> tuple[str, str | None]:
        controls = self.hub.controls(device_id)
        onoff = status_key(controls.onoff or DEFAULT_ONOFF) or "output"
        level = status_key(controls.level.path) if controls.level else None
        return onoff, level

    def _snapshot(self, device_id: int) -> Memory | None:
        device = self.hub.devices.get(device_id)
        if device is None:
            return None
        onoff, level = self._keys(device_id)
        on = device.status.get(onoff)
        if not isinstance(on, bool):
            return None
        snapshot: Memory = {"on": on}
        if level is not None and _is_number(device.status.get(level)):
            snapshot["level"] = device.status[level]
        return snapshot

    def _write_for(self, device_id: int) -> dict[str, Any] | None:
        device = self.hub.devices.get(device_id)
        desired = POLICIES[self.policy](self.memory.get(str(device_id)))
        if device is None or not desired or not isinstance(desired.get("on"), bool):
            return None
        onoff, level = self._keys(device_id)
        payload: dict[str, Any] = {onoff: desired["on"]}
        if desired["on"] and level is not None and _is_number(desired.get("level")):
            payload[level] = desired["level"]
        if all(device.status.get(key) == value for key, value in payload.items()):
            return None
        return payload

    def _schedule_restore(self, module_id: int) -> None:
        self._pending.add(module_id)
        self._schedule("restore", SETTLE_DELAY, self._start_restore)

    def _schedule(self, name: str, delay: float, action: Callable[[], None]) -> None:
        if (cancel := self._timers.pop(name, None)) is not None:
            cancel()

        @callback
        def fire(_: datetime) -> None:
            self._timers.pop(name, None)
            action()

        self._timers[name] = async_call_later(self.hass, delay, fire)

    def _start_restore(self) -> None:
        modules, self._pending = sorted(self._pending), set()
        self.entry.async_create_task(
            self.hass, self._async_restore(modules), f"{DOMAIN} restore {self.hub.site_id}"
        )

    async def _async_restore(self, modules: list[int]) -> None:
        writes = [
            (device_id, payload)
            for device_id, module_id in self._module_of.items()
            if module_id in modules
            and self._online.get(module_id)
            and (payload := self._write_for(device_id)) is not None
        ]
        restored: list[int] = []
        failed: list[int] = []
        for index, (device_id, payload) in enumerate(writes):
            if index:
                await asyncio.sleep(WRITE_INTERVAL)
            if await self._async_write(device_id, payload):
                restored.append(device_id)
            else:
                failed.append(device_id)
        if not writes:
            _LOGGER.debug("Modules %s are back; selected outputs already match", modules)
            return
        self.last_restore = {
            "time": dt_util.utcnow().isoformat(),
            "modules": modules,
            "restored": restored,
            "failed": failed,
        }
        self._save()
        self.hass.bus.async_fire(
            EVENT_OUTPUTS_RESTORED,
            {
                "entry_id": self.entry.entry_id,
                "site_id": self.hub.site_id,
                "module_ids": modules,
                "device_ids": restored,
                "failed_device_ids": failed,
                "restored": len(restored),
                "failed": len(failed),
            },
        )
        await self._async_notify(restored, failed)

    async def _async_write(self, device_id: int, payload: dict[str, Any]) -> bool:
        for attempt in range(2):
            try:
                if list(payload) == ["output"]:
                    await self.hub.async_set_output(device_id, payload["output"])
                else:
                    await self.hub.async_patch_status(device_id, payload)
            except HomeAssistantError as err:
                cause = type(err.__cause__ or err).__name__
                if attempt:
                    _LOGGER.warning("Could not restore output %s (%s)", device_id, cause)
                    return False
                _LOGGER.info("Restoring output %s failed (%s); retrying", device_id, cause)
                await asyncio.sleep(WRITE_INTERVAL)
            else:
                return True
        return False

    async def _async_notify(self, restored: list[int], failed: list[int]) -> None:
        strings = await async_get_translations(
            self.hass, self.hass.config.language, "exceptions", [DOMAIN]
        )

        def text(key: str, **placeholders: Any) -> str:
            template = strings.get(f"component.{DOMAIN}.exceptions.{key}.message", key)
            return template.format(**placeholders)

        def names(device_ids: list[int]) -> str:
            return "\n".join(f"- {self._name(device_id)}" for device_id in device_ids)

        lines = []
        if restored:
            lines.append(text("outputs_restored", devices=names(restored)))
        if failed:
            lines.append(text("outputs_not_restored", devices=names(failed)))
        persistent_notification.async_create(
            self.hass,
            "\n\n".join(lines),
            title=text("outputs_restored_title", count=len(restored)),
            notification_id=f"{DOMAIN}_{self.entry.entry_id}_restored",
        )

    def _name(self, device_id: int) -> str:
        device = self.hub.devices.get(device_id)
        return (device.name if device is not None else "") or str(device_id)

    def _save(self) -> None:
        self._store.async_delay_save(self._data, SAVE_DELAY)

    def _data(self) -> dict[str, Any]:
        return {
            "outputs": self.memory,
            "modules": self.module_state,
            "last_power_loss": self.last_power_loss.isoformat() if self.last_power_loss else None,
            "last_restore": self.last_restore,
        }
