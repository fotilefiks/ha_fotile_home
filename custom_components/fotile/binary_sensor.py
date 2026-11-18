"""Stove burner state binary sensors (read-only)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEVICE_KIND_DISHWASHER,
    DEVICE_KIND_STOVE,
    SID_LEFT_STOVE,
    SID_RIGHT_STOVE,
)
from .coordinator import FotileDataUpdateCoordinator
from .core.mapping import to_bool
from .entity import FotileEntity

_LOGGER = logging.getLogger(__name__)

# (status field, entity key suffix, required sid)
STOVE_BURNERS: list[tuple[str, str, str]] = [
    ("left_stove_state", "left_stove", SID_LEFT_STOVE),
    ("right_stove_state", "right_stove", SID_RIGHT_STOVE),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FotileDataUpdateCoordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = []
    for device in coordinator.selected_devices.values():
        if DEVICE_KIND_DISHWASHER in device.kinds:
            entities.append(FotileDishwasherOnlineSensor(coordinator, device))

        if DEVICE_KIND_STOVE not in device.kinds:
            continue
        for status_field, entity_key, sid in STOVE_BURNERS:
            if device.supports_service(sid):
                entities.append(
                    FotileStoveBurnerSensor(
                        coordinator, device, status_field, entity_key
                    )
                )

    if entities:
        _LOGGER.debug("Adding %d stove burner sensor(s)", len(entities))
        async_add_entities(entities)


class FotileStoveBurnerSensor(FotileEntity, BinarySensorEntity):
    """On/off state of one stove burner."""

    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(
        self,
        coordinator: FotileDataUpdateCoordinator,
        device: Any,
        status_field: str,
        entity_key: str,
    ) -> None:
        super().__init__(coordinator, device, entity_key)
        self._status_field = status_field
        self._attr_translation_key = entity_key
        self._attr_name = None

    @property
    def is_on(self) -> bool | None:
        value = self._device.get_status_value(self._status_field)
        if value is None:
            return None
        return to_bool(value)


class FotileDishwasherOnlineSensor(FotileEntity, BinarySensorEntity):
    """Connectivity sensor that remains available while the dishwasher is offline."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: FotileDataUpdateCoordinator, device: Any) -> None:
        super().__init__(coordinator, device, "dishwasher_online")
        self._attr_name = "在线"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def is_on(self) -> bool:
        return self._device.online
