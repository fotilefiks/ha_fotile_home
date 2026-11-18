"""Response parsing and field mapping (no aiohttp/HA deps)."""

from __future__ import annotations

from typing import Any

from ..const import (
    FIELD_MAP_DEVICE_INFO,
    FIELD_MAP_DEVICE_TOP,
    KEY_DATA,
    KEY_DEVICES,
    KEY_SERVICE_ID,
    KEY_SERVICE_TYPE,
    KEY_SERVICES,
    KEY_STATUS,
    KEY_TIMESTAMP,
    STATUS_FIELD_MAP,
)

__all__ = [
    "extract_device_list",
    "extract_service_ids",
    "flatten_service_data",
    "map_app_device_fields",
    "map_app_shadow",
    "map_device_fields",
    "map_status_fields",
    "to_bool",
    "to_float",
    "to_int",
]


def map_app_device_fields(device: Any) -> dict[str, Any] | None:
    """Map a 方太幸福家 App device-list object to internal device fields."""
    if not isinstance(device, dict):
        return None
    device_id = device.get("id") or device.get("deviceId")
    if device_id is None:
        return None
    return {
        "device_id": str(device_id),
        "name": device.get("name") or device.get("productName") or str(device_id),
        "device_type": device.get("productName") or "",
        "model": device.get("type") or "",
        "manufacturer": "Fotile",
        "product_id": str(device.get("product_id") or device.get("productId") or ""),
        "serial_number": str(device.get("sn") or ""),
        "service_ids": [],
        "service_types": [],
        "online": False,
        "_raw": device,
        "_source": "app",
    }


def map_app_shadow(shadow: Any) -> dict[str, Any]:
    """Map an App batchQueryShadow object to online and flattened fields."""
    result: dict[str, Any] = {"online": False, "_flat": {}}
    if not isinstance(shadow, dict):
        return result
    result["online"] = to_bool(shadow.get("online"), default=False)
    shadow_data = shadow.get("shadowData")
    properties = (
        shadow_data.get("propertyPairs") if isinstance(shadow_data, dict) else None
    )
    if not isinstance(properties, dict):
        return result
    result["_flat"] = {
        f"AppState.{key}": value
        for key, value in properties.items()
        if isinstance(value, (str, int, float, bool))
    }
    return result


def extract_device_list(payload: dict[str, Any]) -> list[Any]:
    devices = payload.get(KEY_DEVICES)
    if not isinstance(devices, list):
        return []
    return devices


def extract_service_ids(device: dict[str, Any]) -> list[str]:
    """Capability declarations (services[].sid). Unique, order preserved."""
    if not isinstance(device, dict):
        return []
    services = device.get(KEY_SERVICES)
    if not isinstance(services, list):
        return []
    sids: list[str] = []
    for svc in services:
        if not isinstance(svc, dict):
            continue
        sid = svc.get(KEY_SERVICE_ID)
        if isinstance(sid, str) and sid and sid not in sids:
            sids.append(sid)
    return sids


def extract_service_types(device: dict[str, Any]) -> list[str]:
    """services[].st list, unique, order preserved."""
    if not isinstance(device, dict):
        return []
    services = device.get(KEY_SERVICES)
    if not isinstance(services, list):
        return []
    types: list[str] = []
    for svc in services:
        if not isinstance(svc, dict):
            continue
        st = svc.get(KEY_SERVICE_TYPE)
        if isinstance(st, str) and st and st not in types:
            types.append(st)
    return types


def map_device_fields(device: Any) -> dict[str, Any]:
    """Map a DeviceDiscovery device object to the internal structure."""
    if not isinstance(device, dict):
        return {
            "device_id": None,
            "name": None,
            "model": None,
            "device_type": None,
            "manufacturer": None,
            "product_id": None,
            "serial_number": None,
            "service_ids": [],
            "service_types": [],
            "_raw": device,
        }

    dev_info = device.get("devInfo")
    if not isinstance(dev_info, dict):
        dev_info = {}

    mapped: dict[str, Any] = {}
    for internal, api_key in FIELD_MAP_DEVICE_TOP.items():
        mapped[internal] = device.get(api_key)
    for internal, api_key in FIELD_MAP_DEVICE_INFO.items():
        mapped[internal] = dev_info.get(api_key)

    mapped["service_ids"] = extract_service_ids(device)
    mapped["service_types"] = extract_service_types(device)
    mapped["_raw"] = device
    return mapped


def flatten_service_data(services: Any) -> dict[str, Any]:
    """Flatten snapshot services[] to {"sid.attr": value}."""
    if not isinstance(services, list):
        return {}

    flat: dict[str, Any] = {}
    for svc in services:
        if not isinstance(svc, dict):
            continue
        sid = svc.get(KEY_SERVICE_ID)
        if not isinstance(sid, str) or not sid:
            continue

        ts = svc.get(KEY_TIMESTAMP)
        if ts is not None:
            flat[f"{sid}.__ts"] = ts

        data = svc.get(KEY_DATA)
        if not isinstance(data, dict):
            continue
        for attr, value in data.items():
            flat[f"{sid}.{attr}"] = value

    return flat


def map_status_fields(snapshot_device: Any) -> dict[str, Any]:
    """Map a snapshot device to the internal status dict."""
    result: dict[str, Any] = {"online": False, "_flat": {}}
    if not isinstance(snapshot_device, dict):
        return result

    status = snapshot_device.get(KEY_STATUS)
    result["online"] = isinstance(status, str) and status.strip().lower() == "online"

    flat = flatten_service_data(snapshot_device.get(KEY_SERVICES))
    result["_flat"] = flat

    for internal, mapping in STATUS_FIELD_MAP.items():
        sid, attr = mapping
        result[internal] = flat.get(f"{sid}.{attr}")

    return result


def find_snapshot_device(
    payload: dict[str, Any], device_id: str
) -> dict[str, Any] | None:
    """Find a device in a snapshot response by thirdPartyDevId."""
    for device in extract_device_list(payload):
        if not isinstance(device, dict):
            continue
        if str(device.get("thirdPartyDevId", "")) == str(device_id):
            return device
    return None


def to_bool(value: Any, default: bool = False) -> bool:
    """Normalize cloud boolean forms (1/0, true/false, on/off, ...) to bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "on", "yes", "open"}
    return default


def to_int(value: Any, default: int | None = None) -> int | None:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
