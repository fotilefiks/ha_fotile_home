"""Fotile dishwasher wash-mode selector."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEVICE_KIND_DISHWASHER,
    DISHWASHER_1025_WORK_MODE_MAP,
    DISHWASHER_SELECTABLE_WORK_MODES,
)
from .coordinator import FotileDataUpdateCoordinator
from .core.device import FotileDevice
from .entity import FotileEntity

OPTIONS = tuple(
    DISHWASHER_1025_WORK_MODE_MAP[mode] for mode in DISHWASHER_SELECTABLE_WORK_MODES
)
NAME_TO_MODE = {
    DISHWASHER_1025_WORK_MODE_MAP[mode]: mode
    for mode in DISHWASHER_SELECTABLE_WORK_MODES
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FotileDataUpdateCoordinator = entry.runtime_data
    entities = [
        FotileDishwasherModeSelect(coordinator, device)
        for device in coordinator.selected_devices.values()
        if DEVICE_KIND_DISHWASHER in device.kinds
    ]
    if entities:
        async_add_entities(entities)


class FotileDishwasherModeSelect(FotileEntity, SelectEntity):
    """Pick the mode that the Start button will send."""

    _attr_icon = "mdi:dishwasher"
    _attr_options = OPTIONS

    def __init__(
        self,
        coordinator: FotileDataUpdateCoordinator,
        device: FotileDevice,
    ) -> None:
        super().__init__(coordinator, device, "dishwasher_mode")
        self._attr_name = "洗涤模式"

    @property
    def current_option(self) -> str:
        mode = self.coordinator.selected_dishwasher_mode(self._device.device_id)
        return DISHWASHER_1025_WORK_MODE_MAP.get(mode, OPTIONS[0])

    async def async_select_option(self, option: str) -> None:
        mode = NAME_TO_MODE.get(option)
        if mode is None:
            return
        self.coordinator.set_selected_dishwasher_mode(self._device.device_id, mode)
        self.async_write_ha_state()
