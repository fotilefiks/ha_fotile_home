"""Fotile device model abstraction."""

from __future__ import annotations

import time
from typing import Any

from ..const import (
    DEVICE_KIND_BY_SID,
    DEVICE_KIND_DISHWASHER,
    DISHWASHER_MODEL_MARKERS,
    DISHWASHER_PRODUCT_PREFIXES,
    DISHWASHER_STATUS_KEYS,
)


class FotileDevice:
    """Wraps a device's identity and current status for HA entities."""

    def __init__(self, device_info: dict[str, Any]) -> None:
        self.device_id: str = device_info.get("device_id", "")
        self.name: str = device_info.get("name", "") or self.device_id
        self.device_type: str = device_info.get("device_type", "")
        self.model: str = device_info.get("model", "")
        # The spec has no firmware-version field; keep the attribute so
        # DeviceInfo construction never fails.
        self.firmware_version: str = device_info.get("firmware_version", "")
        self.online: bool = device_info.get("online", False)

        # Capability declarations from DeviceDiscovery services[].sid / .st.
        self.service_ids: list[str] = list(device_info.get("service_ids") or [])
        self.service_types: list[str] = list(device_info.get("service_types") or [])
        # prodId, used as Command.prodId (optional, spec 2.3.7.2).
        self.product_id: str = device_info.get("product_id", "") or ""

        self._status: dict[str, Any] = {}
        # Last successful status refresh; None means never.
        self._status_updated_at: float | None = None

    def update_info(self, device_info: dict[str, Any]) -> None:
        """Update identity fields; online is left untouched (list has no status)."""
        self.name = device_info.get("name") or self.device_id
        self.device_type = device_info.get("device_type", "") or self.device_type
        self.model = device_info.get("model", "") or self.model
        self.product_id = device_info.get("product_id", "") or self.product_id
        if device_info.get("service_ids"):
            self.service_ids = list(device_info["service_ids"])
        if device_info.get("service_types"):
            self.service_types = list(device_info["service_types"])

    def supports_service(self, sid: str) -> bool:
        """True if declared; an empty service list is treated as supported."""
        if not self.service_ids:
            return True
        return sid in self.service_ids

    @property
    def flat_status(self) -> dict[str, Any]:
        """Raw snapshot attributes as ``{sid.attr: value}``."""
        flat = self._status.get("_flat")
        return flat if isinstance(flat, dict) else {}

    @property
    def is_dishwasher(self) -> bool:
        """Best-effort dishwasher detection for the diagnostic integration."""
        identity = " ".join((self.model, self.name, *self.service_ids)).upper()
        if any(marker in identity for marker in DISHWASHER_MODEL_MARKERS):
            return True
        if self.product_id.upper().startswith(DISHWASHER_PRODUCT_PREFIXES):
            return True

        attrs = {
            str(key).split(".", 1)[-1]
            for key in self.flat_status
            if not str(key).endswith(".__ts")
        }
        return bool(attrs & DISHWASHER_STATUS_KEYS)

    @property
    def kinds(self) -> list[str]:
        """Device categories matched via services[].sid (not devType)."""
        declared = set(self.service_ids)
        kinds = [
            kind
            for kind, feature_sids in DEVICE_KIND_BY_SID.items()
            if feature_sids & declared
        ]
        if self.is_dishwasher and DEVICE_KIND_DISHWASHER not in kinds:
            kinds.append(DEVICE_KIND_DISHWASHER)
        return kinds

    @property
    def status(self) -> dict[str, Any]:
        return self._status

    def update_status(self, status: dict[str, Any]) -> None:
        """Apply a new snapshot: store state, record timestamp, set online."""
        self._status = status
        self._status_updated_at = status.get("_fetched_at") or time.time()
        # Online status comes only from DeviceSnapshot.status.
        self.online = bool(status.get("online", False))

    def mark_status_stale(self) -> None:
        """A status refresh failed. Keep the old value; freshness check fails."""
        # Intentionally does not touch _status_updated_at.

    @property
    def status_updated_at(self) -> float | None:
        return self._status_updated_at

    def is_status_fresh(self, max_age_seconds: float) -> bool:
        if self._status_updated_at is None:
            return False
        return (time.time() - self._status_updated_at) <= max_age_seconds

    def get_status_value(self, key: str, default: Any = None) -> Any:
        """Read a mapped internal status field, or default if absent.

        For unmapped raw attributes use status["_flat"][f"{sid}.{attr}"].
        """
        return self._status.get(key, default)

    def __repr__(self) -> str:
        age = (
            None
            if self._status_updated_at is None
            else round(time.time() - self._status_updated_at, 1)
        )
        return (
            f"<FotileDevice id={self.device_id!r} name={self.name!r} "
            f"type={self.device_type!r} online={self.online} status_age={age}s>"
        )
