"""Constants for the Automic Heating integration."""

from datetime import timedelta

DOMAIN = "automic_heating"
ENTITY_ID_PREFIX = "uc4"

CONF_CLIENT = "client"
CONF_TOKEN = "token"
CONF_TOKEN_NAME = "token_name"
CONF_TOKEN_EXPIRES = "token_expires"
CONF_VARA_SUMMARY = "vara_summary"
CONF_VARA_WEEKDAY = "vara_weekday"
CONF_VARA_WEEKEND = "vara_weekend"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_URL = "<AutomicRestEndpoint>"
DEFAULT_CLIENT = 1
DEFAULT_VARA_SUMMARY = "HEATING.VARA.ROOM.INFORMATION.SUMMARY"
DEFAULT_VARA_WEEKDAY = "HEATING.VARA.ROOM.INFORMATION"
DEFAULT_VARA_WEEKEND = "HEATING.VARA.ROOM.INFORMATION.WEEKEND"
DEFAULT_SCAN_INTERVAL = 15  # seconds

TOKEN_PREFIX = "HA_BRIDGE_"
TOKEN_LIFETIME = timedelta(days=90)
TOKEN_RENEW_BEFORE = timedelta(days=14)
TOKEN_CHECK_INTERVAL = timedelta(hours=6)

# Header names (without the leading "_") used to locate columns.
COL_ACT_TEMP = "actTemp"
COL_HEATING_MODE = "HeatingMode"
COL_INFRA = "InfraHeating"
COL_FLOOR = "FloorHeating"
COL_MUST_TEMP = "MustTemp"
COL_DAY = "Day"
COL_NIGHT = "Night"
COL_MODE = "Mode"

# _Mode(0=off/1=infra/2=floor/3=both/4=manual)
MODES = {0: "off", 1: "infra", 2: "floor", 3: "both", 4: "manual"}
MODE_IDS = {name: mode_id for mode_id, name in MODES.items()}

SCHEDULE_WEEKDAY = "weekday"
SCHEDULE_WEEKEND = "weekend"

MIN_TEMP = 5.0
MAX_TEMP = 30.0
TEMP_STEP = 0.5
