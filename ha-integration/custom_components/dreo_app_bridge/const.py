DOMAIN = "dreo_app_bridge"
CONF_LICENSE = "license_json"
CONF_FAN_HOST = "fan_host"
CONF_USER_ID = "user_id"
CONF_REGION = "region"
DEFAULT_REGION = "eu"
DEFAULT_UID = "<YOUR_USER_ID>"
DEVAPI = {"eu": "https://device-api-eu.dreo-cloud.com",
          "us": "https://device-api-us.dreo-cloud.com"}
CLIENT_ID = "<set DREO_CLIENT_ID>"
CLIENT_SECRET = "<set DREO_CLIENT_SECRET>"
UA = "dreo/hefi 1.0.3"
META = {"moduleHardwareModel": "HeFi", "moduleFirmwareVersion": "3.8.13",
        "mcuHardwareModel": "FP6063U/EU", "mcuFirmwareVersion": "3.6.4"}
ACTUATED = ("lighton", "windlevel", "colortemp", "fanon", "brightness", "mode", "muteon")
MIRROR_DEFAULTS = {"scheid": 0, "scheon": False}
