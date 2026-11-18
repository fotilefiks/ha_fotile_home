"""Read-only diagnostic sensors for Fotile dishwashers."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEVICE_KIND_DISHWASHER,
    DISHWASHER_1025_WORK_MODE_MAP,
    DISHWASHER_1025_WORK_STATE_MAP,
)
from .coordinator import FotileDataUpdateCoordinator
from .core.device import FotileDevice
from .core.mapping import to_int
from .entity import FotileEntity

_LOGGER = logging.getLogger(__name__)

FIELD_NAMES: dict[str, str] = {
    "PowerSwitchAll": "电源原始值",
    "WorkState": "工作状态",
    "RunState": "运行状态",
    "WorkMode": "当前洗涤模式",
    "ClRemTime": "剩余时间",
    "SetWorkTime": "设定工作时间",
    "StRemTime": "烘干时长",
    "StoreTotalTime": "保洁存储",
    "SetAppointmentTime": "预约时间原始值",
    "DoorLockSta": "门锁状态",
    "ErrorNum": "故障码",
    "Reminder": "设备提醒",
    "DetergentLevel": "洗碗液余量",
    "SoftensaltLevel": "软水盐余量",
    "Turbidity": "浊度",
    "GSCWorkSta": "果蔬篮状态",
    "GSCRunSta": "果蔬篮运行状态",
    "GSCWorkMode": "果蔬篮当前模式",
    "GSCSetWorkT": "果蔬篮设定时间",
    "GSCClRemT": "果蔬篮剩余时间",
    "GSCErrorNum": "果蔬篮故障码",
    "AutoDrain": "排水状态",
    "GSCAutoDrain": "果蔬排水状态",
    "RemoteAuth": "远程授权",
    "AuthType": "授权类型",
    "NewRemoteAuth": "新远程授权",
}

FIELD_ICONS: dict[str, str] = {
    "PowerSwitchAll": "mdi:power",
    "WorkState": "mdi:state-machine",
    "RunState": "mdi:play-circle-outline",
    "WorkMode": "mdi:dishwasher",
    "ClRemTime": "mdi:timer-sand",
    "SetWorkTime": "mdi:clock-digital",
    "StoreTotalTime": "mdi:calendar-range",
    "SetAppointmentTime": "mdi:clock-outline",
    "DoorLockSta": "mdi:door-closed-lock",
    "ErrorNum": "mdi:alert-circle-outline",
    "Reminder": "mdi:bell-outline",
    "DetergentLevel": "mdi:dishwasher-fluid",
    "SoftensaltLevel": "mdi:shaker-outline",
    "Turbidity": "mdi:water-opacity",
    "AutoDrain": "mdi:water-pump",
}

TIME_FIELDS = {"ClRemTime", "SetWorkTime", "StRemTime", "GSCSetWorkT", "GSCClRemT"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one sensor per dishwasher status field returned by the cloud."""
    coordinator: FotileDataUpdateCoordinator = entry.runtime_data
    entities: list[FotileDishwasherSensor] = []

    for device in coordinator.selected_devices.values():
        if DEVICE_KIND_DISHWASHER not in device.kinds:
            continue

        seen: set[str] = set()
        for raw_key, raw_value in device.flat_status.items():
            if raw_key.endswith(".__ts") or raw_key in seen:
                continue
            if not isinstance(raw_value, (str, int, float, bool)):
                continue
            seen.add(raw_key)
            entities.append(FotileDishwasherSensor(coordinator, device, raw_key))

    if entities:
        _LOGGER.debug("Adding %d dishwasher diagnostic sensor(s)", len(entities))
        async_add_entities(entities)


class FotileDishwasherSensor(FotileEntity, SensorEntity):
    """Read-only view of one dishwasher cloud attribute."""

    def __init__(
        self,
        coordinator: FotileDataUpdateCoordinator,
        device: FotileDevice,
        raw_key: str,
    ) -> None:
        super().__init__(coordinator, device, f"dishwasher_{raw_key}")
        self._raw_key = raw_key
        sid, _, attr = raw_key.partition(".")
        self._sid = sid
        self._attr_name = FIELD_NAMES.get(attr, f"{attr}（原始字段）")
        self._attr_icon = FIELD_ICONS.get(attr, "mdi:dishwasher")
        if attr in TIME_FIELDS:
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_native_unit_of_measurement = "min"

    @property
    def native_value(self) -> Any:
        value = self._device.flat_status.get(self._raw_key)
        if value is None:
            return None

        attr = self._raw_key.partition(".")[2]
        number = to_int(value)

        if attr in TIME_FIELDS and number is not None:
            hours, minutes = divmod(number, 256)
            if 0 <= minutes < 60 and 0 <= hours < 24:
                return hours * 60 + minutes

        if attr == "WorkState" and number is not None:
            if number == 0:
                power = to_int(
                    self._device.flat_status.get("AppState.PowerSwitchAll")
                )
                return "待机" if power else "已关机"
            mapped = DISHWASHER_1025_WORK_STATE_MAP.get(number)
            return mapped if mapped is not None else value

        if attr == "WorkMode" and number is not None:
            mapped = DISHWASHER_1025_WORK_MODE_MAP.get(number)
            return mapped if mapped is not None else value

        if attr == "ErrorNum" and number == 0:
            return "无故障"

        if attr == "DoorLockSta" and number is not None:
            return "已上锁" if number else "未上锁"

        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "raw_key": self._raw_key,
            "service_id": self._sid,
            "raw_value": self._device.flat_status.get(self._raw_key),
            "product_id": self._device.product_id,
            "service_ids": self._device.service_ids,
            "diagnostic_only": True,
        }
