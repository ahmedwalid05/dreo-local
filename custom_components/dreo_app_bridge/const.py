DOMAIN = "dreo_app_bridge"
CONF_LICENSE = "license_json"
CONF_FAN_HOST = "fan_host"
CONF_USER_ID = "user_id"
CONF_REGION = "region"
CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
DEFAULT_REGION = "eu"
# No personal defaults are shipped. Supply these in the config flow.
DEFAULT_UID = ""
DEVAPI = {"eu": "https://device-api-eu.dreo-cloud.com",
          "us": "https://device-api-us.dreo-cloud.com"}
UA = "dreo/hefi 1.0.3"
META = {"moduleHardwareModel": "HeFi", "moduleFirmwareVersion": "3.8.13",
        "mcuHardwareModel": "FP6063U/EU", "mcuFirmwareVersion": "3.6.4"}
ACTUATED = ("lighton", "windlevel", "colortemp", "fanon", "brightness", "mode", "muteon")
MIRROR_DEFAULTS = {"scheid": 0, "scheon": False}
