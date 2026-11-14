"""The Dreo App Bridge: keeps the official Dreo app working for an
ESPHome-flashed Dreo device by impersonating it to the Dreo cloud — running
inside Home Assistant instead of on a desktop."""
import logging, threading

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_FAN_HOST,
                    CONF_REGION, CONF_USER_ID, DEVAPI, DOMAIN)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    lic = {"sn": entry.data["sn"], "signature": entry.data["signature"]}
    esp = entry.data[CONF_FAN_HOST]
    if not esp.startswith("http"):
        esp = "http://" + esp
    status: dict = {"state": "starting", "error": None, "sn": lic["sn"]}
    stop = threading.Event()

    from .bridge import run_bridge
    thread = threading.Thread(
        target=run_bridge,
        args=(DEVAPI[entry.data[CONF_REGION]], esp, lic,
              entry.data[CONF_USER_ID], entry.data[CONF_CLIENT_ID],
              entry.data[CONF_CLIENT_SECRET], stop, status),
        name="dreo_app_bridge", daemon=True)
    thread.start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "thread": thread, "stop": stop, "status": status}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if data:
        data["stop"].set()
        data["thread"].join(timeout=15)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
