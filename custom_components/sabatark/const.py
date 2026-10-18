"""Constants for the Sabatark integration."""

from homeassistant.const import Platform

DOMAIN = "sabatark"

CONF_TOKEN = "token"
CONF_USER_ID = "user_id"
CONF_SITE_ID = "site_id"
CONF_SESSION = "session"

MANUFACTURER = "EnLife"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.COVER,
    Platform.EVENT,
    Platform.LIGHT,
    Platform.LOCK,
    Platform.SENSOR,
    Platform.SWITCH,
]

RECONNECT_INITIAL = 5.0
RECONNECT_MAX = 300.0
UNAVAILABLE_GRACE = 30.0
