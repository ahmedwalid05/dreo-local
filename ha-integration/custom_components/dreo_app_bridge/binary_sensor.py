"""Connected status for the Dreo App Bridge."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass, BinarySensorEntity)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    status = hass.data[DOMAIN][entry.entry_id]["status"]
    async_add_entities([DreoBridgeConnected(hass, entry, status)])


class DreoBridgeConnected(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTED
    _attr_name = "Connected"

    def __init__(self, hass, entry, status):
        self._hass = hass
        self._entry = entry
        self._status = status
        self._attr_unique_id = f"{entry.entry_id}_connected"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["sn"])},
            name="Dreo App Bridge", manufacturer="Dreo (ESPHome bridge)")

    @property
    def is_on(self) -> bool:
        return self._status.get("state") == "connected"

    @property
    def extra_state_attributes(self):
        return {"state": self._status.get("state"),
                "error": self._status.get("error"),
                "sn": self._status.get("sn")}
