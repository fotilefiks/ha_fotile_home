"""Data update coordinator for Fotile devices."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CONF_DEVICES_FILTER,
    DEFAULT_SCAN_INTERVAL,
    DEVICE_LIST_CACHE_TTL,
    DOMAIN,
    STATUS_STALE_THRESHOLD,
)
from .core.api import (
    FotileApiError,
    FotileAuthError,
    FotileClient,
    FotileConnectionError,
    is_ha_config_entry_exception,
)
from .core.device import FotileDevice

if TYPE_CHECKING:
    from .types import FotileConfigEntry

_LOGGER = logging.getLogger(__name__)


class FotileDataUpdateCoordinator(DataUpdateCoordinator[dict[str, FotileDevice]]):
    """Fetches and distributes the state of all Fotile devices."""

    config_entry: FotileConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: FotileClient,
        entry: FotileConfigEntry,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self._devices: dict[str, FotileDevice] = {}
        # (timestamp, raw device info list)
        self._device_list_cache: tuple[float, list[dict[str, Any]]] | None = None
        # Scale the freshness threshold with the polling interval so a long
        # interval does not flip entities to unavailable between polls.
        self._status_stale_threshold: float = max(
            STATUS_STALE_THRESHOLD, scan_interval * 2
        )
        self._selected_dishwasher_modes: dict[str, int] = {}

    @property
    def devices(self) -> dict[str, FotileDevice]:
        return self._devices

    @property
    def selected_device_ids(self) -> frozenset[str] | None:
        """Selected device IDs; None means all devices (local option only)."""
        selected = self.config_entry.options.get(CONF_DEVICES_FILTER)
        if not selected:
            return None
        return frozenset(str(device_id) for device_id in selected)

    @property
    def selected_devices(self) -> dict[str, FotileDevice]:
        """Devices that entities should be created for."""
        selected = self.selected_device_ids
        if selected is None:
            return self._devices
        return {
            device_id: device
            for device_id, device in self._devices.items()
            if device_id in selected
        }

    def is_selected(self, device_id: str) -> bool:
        """True if the device is not filtered out by the options flow."""
        selected = self.selected_device_ids
        return selected is None or device_id in selected

    def status_is_fresh(self, device_id: str) -> bool:
        """True if the device's status was refreshed recently enough."""
        device = self._devices.get(device_id)
        if device is None:
            return False
        return device.is_status_fresh(self._status_stale_threshold)

    def selected_dishwasher_mode(self, device_id: str) -> int:
        """Selected mode; follows cloud state until locally overridden."""
        if device_id in self._selected_dishwasher_modes:
            return self._selected_dishwasher_modes[device_id]
        device = self._devices.get(device_id)
        if device is None:
            return 0
        value = device.flat_status.get("AppState.WorkMode")
        try:
            mode = int(value)
        except (TypeError, ValueError):
            return 0
        return mode if 0 <= mode <= 4 else 0

    def set_selected_dishwasher_mode(self, device_id: str, mode: int) -> None:
        self._selected_dishwasher_modes[device_id] = mode

    async def _async_get_device_list(self) -> list[dict[str, Any]]:
        now = time.time()
        if (
            self._device_list_cache is not None
            and now - self._device_list_cache[0] < DEVICE_LIST_CACHE_TTL
        ):
            return self._device_list_cache[1]

        device_list = await self.client.get_devices()
        self._device_list_cache = (now, device_list)
        return device_list

    async def _async_update_data(self) -> dict[str, FotileDevice]:
        # 1. Device list (cached).
        try:
            device_list = await self._async_get_device_list()
        except FotileAuthError as err:
            # Credentials invalid -> must become ConfigEntryAuthFailed so HA
            # prompts reauth instead of silently backing off forever.
            raise ConfigEntryAuthFailed(
                f"Fotile credentials rejected: {err.message}"
            ) from err
        except FotileConnectionError as err:
            # List failed. If we still know devices, keep refreshing their
            # status so a single list failure doesn't take everything offline.
            if not self._devices:
                raise UpdateFailed(f"Connection error: {err.message}") from err
            _LOGGER.warning(
                "Failed to refresh Fotile device list, updating %d known device(s): %s",
                len(self._devices),
                err.message,
            )
            device_list = None  # type: ignore[assignment]
        except FotileApiError as err:
            raise UpdateFailed(f"API error: {err.message}") from err

        if device_list is not None:
            # 2. Update existing / discover new.
            for device_info in device_list:
                device_id = device_info["device_id"]
                if device_id not in self._devices:
                    self._devices[device_id] = FotileDevice(device_info)
                    _LOGGER.debug(
                        "Discovered new device: %s (%s, type=%s)",
                        device_info.get("name"),
                        device_id,
                        device_info.get("device_type"),
                    )
                    _LOGGER.debug(
                        "Fotile device identity: id=%s model=%s product=%s services=%s",
                        device_id,
                        device_info.get("model"),
                        device_info.get("product_id"),
                        device_info.get("service_ids"),
                    )
                else:
                    self._devices[device_id].update_info(device_info)

            # 3. Remove devices unbound in the Fotile app.
            current_ids = {d["device_id"] for d in device_list}
            for removed_id in set(self._devices) - current_ids:
                _LOGGER.debug("Device removed: %s", removed_id)
                del self._devices[removed_id]

        # 4. Refresh the status of every selected device concurrently.
        await self._async_refresh_statuses()

        return self._devices

    async def _async_refresh_statuses(self) -> None:
        """Refresh selected snapshots; per-device failures are isolated."""
        device_ids = list(self.selected_devices)
        if not device_ids:
            return

        results = await asyncio.gather(
            *(self.client.get_device_status(device_id) for device_id in device_ids),
            return_exceptions=True,
        )

        for device_id, result in zip(device_ids, results, strict=True):
            device = self._devices.get(device_id)
            if device is None:  # removed during the concurrent refresh
                continue

            if isinstance(result, BaseException):
                # HA config-entry lifecycle exceptions (reauth/not-ready) must
                # propagate unchanged so the framework can act on them.
                if is_ha_config_entry_exception(result):
                    raise result

                if isinstance(result, FotileAuthError):
                    raise ConfigEntryAuthFailed(
                        f"Fotile credentials rejected: {result.message}"
                    ) from result

                device.mark_status_stale()
                _LOGGER.warning(
                    "Failed to get status for device %s: %s",
                    device_id,
                    getattr(result, "message", result),
                )
                continue

            device.update_status(result)
            _LOGGER.debug(
                "Fotile snapshot fields for %s: %s",
                device_id,
                result.get("_flat", {}),
            )
