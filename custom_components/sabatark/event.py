"""Wall-switch gesture events."""

from __future__ import annotations

import logging

from homeassistant.components.event import (
    ATTR_MULTI_PRESS_COUNT,
    ButtonEventType,
    EventDeviceClass,
    EventEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from sabatark import Device, EventLog

from .entity import SabatarkEntity
from .hub import SabatarkConfigEntry, SabatarkHub

_LOGGER = logging.getLogger(__name__)
GESTURES = {
    "singleClick": ButtonEventType.PRESS_END,
    "longPush": ButtonEventType.LONG_PRESS_END,
    "doubleClick": ButtonEventType.MULTI_PRESS_END,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SabatarkConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add an event entity for each wall switch."""
    hub = entry.runtime_data
    async_add_entities(
        SabatarkEvent(hub, device) for device in hub.devices.values() if device.is_switch
    )


class SabatarkEvent(SabatarkEntity, EventEntity):
    """The gestures emitted by one wall switch."""

    _attr_name = None
    _attr_device_class = EventDeviceClass.BUTTON

    def __init__(self, hub: SabatarkHub, device: Device) -> None:
        super().__init__(hub, device, "event")
        self._attr_event_types = list(GESTURES.values())

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hub.async_subscribe_gestures(self.device_id, self._handle_gesture)
        )

    @callback
    def _handle_gesture(self, event: EventLog) -> None:
        if event.path != "/status/input":
            return
        if (event_type := GESTURES.get(event.gesture)) is None:
            _LOGGER.debug("Ignoring unknown switch gesture %s", event.gesture)
            return
        attributes = {ATTR_MULTI_PRESS_COUNT: 2} if event.gesture == "doubleClick" else None
        self._trigger_event(event_type, attributes)
        self.async_write_ha_state()
