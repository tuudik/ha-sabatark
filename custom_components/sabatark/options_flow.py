"""Options for modelling access devices."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

import probatio
from homeassistant.config_entries import ConfigFlowResult, OptionsFlowWithReload
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from sabatark import Device

from .hub import SabatarkConfigEntry, SabatarkHub


def access_options(entry: SabatarkConfigEntry, device_id: int) -> dict[str, Any]:
    """Return the stored access model, or defaults derived from the device's declared controls."""
    stored = entry.options.get("access", {}).get(str(device_id))
    if stored:
        return {"model": "lock", "paths": ["status.locked"], **stored}
    return access_defaults(getattr(entry, "runtime_data", None), device_id)


def access_defaults(hub: SabatarkHub | None, device_id: int) -> dict[str, Any]:
    """Return the default access model: buttons for 2+ declared buttons, otherwise a lock."""
    buttons = hub.controls(device_id).buttons if hub is not None else []
    options: dict[str, Any] = {
        "model": "buttons" if len(buttons) > 1 else "lock",
        "paths": buttons or ["status.locked"],
    }
    device = hub.devices.get(device_id) if hub is not None else None
    if device is not None and "open" in device.status:
        options.update(state_device=device_id, state_path="status.open")
    return options


def output_paths(device: Device, declared: Iterable[str] = ()) -> list[str]:
    """Return boolean access output paths, including the declared action buttons."""
    return sorted(
        {"status.locked", *declared}
        | {
            f"status.{key}"
            for key, value in device.status.items()
            if key.startswith("output") and isinstance(value, bool)
        }
    )


def status_key(path: str) -> str:
    """Return the key of a direct status path."""
    prefix, separator, key = path.partition(".")
    if prefix != "status" or not separator or not key or "." in key or "/" in key:
        raise ValueError("Expected a direct status path")
    return key


def _select(options: list[Any], *, multiple: bool = False) -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(options=options, multiple=multiple))


class SabatarkOptionsFlow(OptionsFlowWithReload):
    """Choose an access device and configure its entity model."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._device_id = 0
        self._access: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the access device to configure."""
        hub = getattr(self.config_entry, "runtime_data", None)
        if hub is None:
            return self.async_abort(reason="not_loaded")
        devices = [device for device in hub.devices.values() if device.type == "access"]
        if not devices:
            return self.async_abort(reason="no_access_devices")
        if user_input is not None:
            self._device_id = int(user_input["device"])
            self._options = deepcopy(dict(self.config_entry.options))
            self._access = deepcopy(access_options(self.config_entry, self._device_id))
            return await self.async_step_model()
        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(
                {
                    probatio.Required("device", default=str(devices[0].id)): _select(
                        [
                            {"value": str(device.id), "label": device.name or device.type}
                            for device in devices
                        ]
                    ),
                }
            ),
        )

    async def async_step_model(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose lock, garage cover or pulse buttons."""
        if user_input is not None:
            self._access["model"] = user_input["model"]
            if user_input["model"] == "lock":
                self._access = {"model": "lock", "paths": ["status.locked"]}
                return self._save()
            if user_input["model"] == "buttons":
                return await self.async_step_buttons()
            return await self.async_step_cover()
        return self.async_show_form(
            step_id="model",
            data_schema=probatio.Schema(
                {
                    probatio.Required("model", default=self._access["model"]): SelectSelector(
                        SelectSelectorConfig(
                            options=["lock", "cover", "buttons"], translation_key="access_model"
                        )
                    ),
                }
            ),
        )

    async def async_step_buttons(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the output paths exposed as pulse buttons."""
        hub = self.config_entry.runtime_data
        paths = output_paths(hub.devices[self._device_id], hub.controls(self._device_id).buttons)
        errors = {}
        if user_input is not None:
            if user_input["paths"]:
                self._access = {"model": "buttons", "paths": user_input["paths"]}
                return self._save()
            errors["paths"] = "no_paths"
        return self.async_show_form(
            step_id="buttons",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        "paths", default=[path for path in self._access["paths"] if path in paths]
                    ): _select(paths, multiple=True),
                }
            ),
            errors=errors,
        )

    async def async_step_cover(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose a pulse output and a device that reports the opening state."""
        hub = self.config_entry.runtime_data
        sensors = [device for device in hub.devices.values() if self._state_paths(device)]
        if not sensors:
            return self.async_abort(reason="no_state_devices")
        if user_input is not None:
            self._access = {
                "model": "cover",
                "paths": [user_input["path"]],
                "state_device": int(user_input["state_device"]),
                "state_path": self._access.get("state_path", ""),
            }
            return await self.async_step_state()
        paths = output_paths(hub.devices[self._device_id], hub.controls(self._device_id).buttons)
        sensor_ids = {device.id for device in sensors}
        current_sensor = self._access.get("state_device")
        return self.async_show_form(
            step_id="cover",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        "path",
                        default=next(
                            (path for path in self._access["paths"] if path in paths), paths[0]
                        ),
                    ): _select(paths),
                    probatio.Required(
                        "state_device",
                        default=str(
                            current_sensor if current_sensor in sensor_ids else sensors[0].id
                        ),
                    ): _select(
                        [
                            {"value": str(device.id), "label": device.name or device.type}
                            for device in sensors
                        ]
                    ),
                }
            ),
        )

    async def async_step_state(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the boolean status path that is true when the cover is open."""
        if user_input is not None:
            self._access["state_path"] = user_input["state_path"]
            return self._save()
        paths = self._state_paths(
            self.config_entry.runtime_data.devices[self._access["state_device"]]
        )
        current_path = self._access.get("state_path")
        return self.async_show_form(
            step_id="state",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        "state_path", default=current_path if current_path in paths else paths[0]
                    ): _select(paths),
                }
            ),
        )

    @staticmethod
    def _state_paths(device: Device) -> list[str]:
        return [
            f"status.{key}"
            for key, value in device.status.items()
            if key != "online" and isinstance(value, bool)
        ]

    def _save(self) -> ConfigFlowResult:
        self._options.setdefault("access", {})[str(self._device_id)] = self._access
        return self.async_create_entry(title="", data=self._options)
