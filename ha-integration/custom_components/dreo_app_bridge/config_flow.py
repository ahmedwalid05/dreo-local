"""Config flow: paste the factory license, validate against the Dreo API."""
import json, logging
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback

from .const import (CONF_FAN_HOST, CONF_LICENSE, CONF_REGION, CONF_USER_ID,
                    DEFAULT_REGION, DEFAULT_UID, DEVAPI, DOMAIN)

_LOGGER = logging.getLogger(__name__)


def _parse_license(raw: str) -> dict:
    lic = json.loads(raw)
    if not isinstance(lic, dict) or "sn" not in lic or "signature" not in lic:
        raise ValueError("missing sn/signature")
    return lic


class DreoAppBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None):
        errors = {}
        if user_input is not None:
            try:
                lic = _parse_license(user_input[CONF_LICENSE])
            except Exception:
                errors["base"] = "bad_license"
                lic = None
            if lic and not errors:
                await self.async_set_unique_id(lic["sn"])
                self._abort_if_unique_id_configured()
                ok = await self.hass.async_add_executor_job(
                    self._validate, user_input, lic)
                if ok:
                    return self.async_create_entry(
                        title=f"Dreo App Bridge ({lic['sn'][:22]}…)",
                        data={**user_input, "sn": lic["sn"],
                              "signature": lic["signature"]})
                errors["base"] = "register_failed"
        schema = vol.Schema({
            vol.Required(CONF_LICENSE): str,
            vol.Required(CONF_FAN_HOST, default=(user_input or {}).get(CONF_FAN_HOST, "dreo-fan.local")): str,
            vol.Required(CONF_USER_ID, default=DEFAULT_UID): str,
            vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In({"eu": "EU", "us": "US"}),
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    def _validate(user_input: dict, lic: dict) -> bool:
        from .bridge import register
        try:
            register(DEVAPI[user_input[CONF_REGION]], lic["sn"], lic["signature"],
                     user_input[CONF_USER_ID])
            return True
        except Exception as err:
            _LOGGER.warning("dreo_app_bridge validation failed: %s", err)
            return False
