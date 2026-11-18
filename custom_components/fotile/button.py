"""Fotile dishwasher start, pause and cancel buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_KIND_DISHWASHER
from .coordinator import FotileDataUpdateCoordinator
from .core.device import FotileDevice
from .core.mapping import to_int
from .entity import FotileEntity

RUNNING_STATES = {2, 3, 4}
RUNNING_OR_PAUSED_STATES = RUNNING_STATES | {6}


def _work_state(device: FotileDevice) -> int | None:
    return to_int(device.flat_status.get("AppState.WorkState"))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FotileDataUpdateCoordinator = entry.runtime_data
    entities: list[ButtonEntity] = []
    for device in coordinator.selected_devices.values():
        if DEVICE_KIND_DISHWASHER not in device.kinds:
            continue
        entities.extend(
            [
                FotileDishwasherStartButton(coordinator, device),
                FotileDishwasherPauseButton(coordinator, device),
                FotileDishwasherCancelButton(coordinator, device),
            ]
        )
    if entities:
        async_add_entities(entities)


class FotileDishwasherStartButton(FotileEntity, ButtonEntity):
    """Start a new wash, or resume a paused wash."""

    _attr_icon = "mdi:play-circle"

    def __init__(
        self,
        coordinator: FotileDataUpdateCoordinator,
        device: FotileDevice,
    ) -> None:
        super().__init__(coordinator, device, "dishwasher_start")
        self._attr_name = "开始/继续洗涤"

    async def async_press(self) -> None:
        work_state = self._device.flat_status.get("AppState.WorkState")
        try:
            state = int(work_state)
        except (TypeError, ValueError):
            state = 0
        if state == 6:
            command = self.coordinator.client.resume_dishwasher(self._device.device_id)
        else:
            mode = self.coordinator.selected_dishwasher_mode(self._device.device_id)
            command = self.coordinator.client.start_dishwasher(
                self._device.device_id,
                mode,
            )
        await self.async_execute_command(command)
        await self.coordinator.async_request_refresh()


class FotileDishwasherPauseButton(FotileEntity, ButtonEntity):
    """Pause a running wash."""

    _attr_icon = "mdi:pause-circle"

    def __init__(
        self,
        coordinator: FotileDataUpdateCoordinator,
        device: FotileDevice,
    ) -> None:
        super().__init__(coordinator, device, "dishwasher_pause")
        self._attr_name = "暂停洗涤"

    @property
    def available(self) -> bool:
        return super().available and _work_state(self._device) in RUNNING_STATES

    async def async_press(self) -> None:
        await self.async_execute_command(
            self.coordinator.client.pause_dishwasher(self._device.device_id)
        )
        await self.coordinator.async_request_refresh()


class FotileDishwasherCancelButton(FotileEntity, ButtonEntity):
    """Cancel the current wash."""

    _attr_icon = "mdi:stop-circle"

    def __init__(
        self,
        coordinator: FotileDataUpdateCoordinator,
        device: FotileDevice,
    ) -> None:
        super().__init__(coordinator, device, "dishwasher_cancel")
        self._attr_name = "取消洗涤"

    @property
    def available(self) -> bool:
        return (
            super().available and _work_state(self._device) in RUNNING_OR_PAUSED_STATES
        )

    async def async_press(self) -> None:
        await self.async_execute_command(
            self.coordinator.client.stop_dishwasher(self._device.device_id)
        )
        await self.coordinator.async_request_refresh()
