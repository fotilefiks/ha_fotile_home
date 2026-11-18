"""Constants for the Fotile integration."""

from __future__ import annotations

from typing import Any, Final

# Import lazily so this module works without Home Assistant (tests, debug tools).
try:  # pragma: no cover
    from homeassistant.const import Platform
except ImportError:  # pragma: no cover
    Platform = None  # type: ignore[assignment]

DOMAIN: Final = "fotile"
MANUFACTURER: Final = "Fotile"

# ---- OAuth 2.0 (Authorization Code + PKCE) ----
OAUTH_AUTHORIZE_URL: Final = "https://api.fotile.com/api/v1/smsOauthHa/index.html"
OAUTH_TOKEN_URL: Final = "https://api.fotile.com/api/oauth/token"

# Public client id; PKCE makes it safe to ship (no client_secret).
OAUTH_CLIENT_ID: Final = "eHyS5pIN8G"
OAUTH_SCOPES: Final[list[str]] = []
PKCE_CODE_VERIFIER_LENGTH: Final = 128

# ---- HA facade (iot-b2b-delegators /ha/v1) ----
# Flat REST only. CorpId, the cloud-cloud envelope (header / namespace) and the
# enterprise-side protocol stay on the server; the client carries no vendor id.
# All endpoints are POST with "Authorization: Bearer <access_token>":
#   /accept-grant
#   /devices
#   /devices/{deviceId}/snapshot
#   /devices/{deviceId}/command
#   /devices/{deviceId}/subscribe
HA_API_BASE_URL: Final = "https://api.fotile.com/open-cloud/ha/v1"

# The HA facade currently omits some appliance families (including V6A). The
# OAuth token is also accepted by the 方太幸福家 App API, so use this documented
# app protocol as a read-only fallback for devices missing from the facade.
APP_API_BASE_URL: Final = "https://api.fotile.com"
APP_DEVICES_PATH: Final = "/v3/all/homes/devices"
APP_SHADOW_PATH: Final = "/v2/device/batchQueryShadow"
APP_ROUTE_PATH: Final = "/iot-mqttManager/routeService"
APP_API_HEADERS: Final[dict[str, str]] = {
    "Content-Type": "application/json; charset=utf-8",
    "Accept-Encoding": "gzip",
    "X-Source": "android.4.4",
    "X-ModelName": "SM-G9700",
    "X-SoftwareVersion": "Android 9",
    "X-AppVer": "android.3.3.08",
    "User-Agent": "Dart/3.6 (dart:io)",
}

# Only the business codes the client branches on: the facade maps credential
# errors to HTTP 401 and everything else to HTTP 4xx.
CODE_DEVICE_NOT_EXIST: Final = 10009
CODE_COMMAND_NOT_SUPPORT: Final = 10010
CODE_DEVICE_OFFLINE: Final = 10011

# Flat response: code / description plus business fields on the same level.
RESPONSE_KEY_CODE: Final = "code"
KEY_DESCRIPTION: Final = "description"
KEY_DEVICES: Final = "devices"

# Device: id/name at top level, details inside devInfo.
FIELD_MAP_DEVICE_TOP: Final[dict[str, str]] = {
    "device_id": "thirdPartyDevId",
    "name": "devName",
}
FIELD_MAP_DEVICE_INFO: Final[dict[str, str]] = {
    "model": "model",
    "device_type": "devType",
    "manufacturer": "manu",
    "product_id": "prodId",
    "serial_number": "sn",
}

KEY_SERVICES: Final = "services"
KEY_SERVICE_ID: Final = "sid"
KEY_SERVICE_TYPE: Final = "st"
KEY_STATUS: Final = "status"
KEY_DATA: Final = "data"
KEY_TIMESTAMP: Final = "ts"

# Flattened status keys are "{sid}.{attr}".
STATUS_FIELD_MAP: Final[dict[str, tuple[str, str]]] = {
    "power": ("PowerSwitch", "PowerSwitch"),
    "fan_level": ("FanLevel", "FanLevel"),
    "light": ("Light", "Light"),
    # Read-only.
    "left_stove_state": ("LeftStoveState", "LeftStoveState"),
    "right_stove_state": ("RightStoveState", "RightStoveState"),
}

SID_POWER_SWITCH: Final = "PowerSwitch"
SID_FAN_LEVEL: Final = "FanLevel"
SID_LIGHT: Final = "Light"
SID_LEFT_STOVE: Final = "LeftStoveState"
SID_RIGHT_STOVE: Final = "RightStoveState"

# Category is decided by services[].sid; the spec has no devType table.
DEVICE_KIND_RANGE_HOOD: Final = "range_hood"
DEVICE_KIND_STOVE: Final = "stove"
DEVICE_KIND_DISHWASHER: Final = "dishwasher"
DEVICE_KIND_BY_SID: Final[dict[str, frozenset[str]]] = {
    DEVICE_KIND_RANGE_HOOD: frozenset({SID_POWER_SWITCH, SID_FAN_LEVEL, SID_LIGHT}),
    DEVICE_KIND_STOVE: frozenset({SID_LEFT_STOVE, SID_RIGHT_STOVE}),
}

# The cloud facade does not document dishwasher service identifiers yet. These
# markers and raw status fields are shared by the dishwasher families for which
# public protocol traces exist (1025A and 1032A). They are only used to select
# read-only diagnostic entities.
DISHWASHER_MODEL_MARKERS: Final[tuple[str, ...]] = (
    "JBCD",
    "DISH",
    "WASHER",
    "DISHWASHER",
    "DISH_WASH",
)
DISHWASHER_PRODUCT_PREFIXES: Final[tuple[str, ...]] = ("1025", "1032")
DISHWASHER_STATUS_KEYS: Final[frozenset[str]] = frozenset(
    {
        "PowerSwitchAll",
        "WorkState",
        "RunState",
        "WorkMode",
        "ClRemTime",
        "SetWorkTime",
        "StoreTotalTime",
        "DoorLockSta",
        "ErrorNum",
        "Reminder",
        "DetergentLevel",
        "SoftensaltLevel",
        "Turbidity",
        "GSCWorkSta",
        "GSCWorkMode",
        "GSCClRemT",
        "GSCErrorNum",
        "AutoDrain",
        "GSCAutoDrain",
    }
)

DISHWASHER_1025_WORK_STATE_MAP: Final[dict[int, str]] = {
    0: "待机",
    1: "待机",
    2: "运行中",
    3: "运行中",
    4: "运行中",
    5: "已完成",
    6: "已暂停",
    7: "预约中",
}
DISHWASHER_1025_WORK_MODE_MAP: Final[dict[int, str]] = {
    0: "智能洗",
    1: "强力洗",
    2: "标准洗",
    3: "节能洗",
    4: "快速洗",
    5: "漂洗",
    6: "消毒",
    7: "烘干",
    135: "预约",
}
DISHWASHER_SELECTABLE_WORK_MODES: Final[tuple[int, ...]] = (0, 1, 2, 3, 4)

# FanLevel: 0-standby, 1-low, 2-auto, 3-high.
FAN_LEVEL_STANDBY: Final = 0
FAN_LEVEL_LOW: Final = 1
FAN_LEVEL_AUTO: Final = 2
FAN_LEVEL_HIGH: Final = 3

SWITCH_ON_VALUE: Final = 1
SWITCH_OFF_VALUE: Final = 0

DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 300
DEVICE_LIST_CACHE_TTL: Final = 300
STATUS_STALE_THRESHOLD: Final = 120

CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_DEVICES_FILTER: Final = "devices_filter"
CONF_THIRD_PARTY_USER_ID: Final = "third_party_user_id"

if Platform is None:  # pragma: no cover
    PLATFORMS: Final[list[Any]] = []
else:
    PLATFORMS: Final[list[Platform]] = [
        Platform.FAN,
        Platform.LIGHT,
        Platform.SWITCH,
        Platform.SELECT,
        Platform.BUTTON,
        Platform.SENSOR,
        Platform.BINARY_SENSOR,
    ]
