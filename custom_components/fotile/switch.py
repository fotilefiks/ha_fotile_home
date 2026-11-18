"""Fotile dishwasher power switch."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_KIND_DISHWASHER
from .coordinator import FotileDataUpdateCoordinator
from .core.device import FotileDevice
from .core.mapping import to_bool
from .entity import FotileEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FotileDataUpdateCoordinator = entry.runtime_data
    entities = [
        FotileDishwasherPowerSwitch(coordinator, device)
        for device in coordinator.selected_devices.values()
        if DEVICE_KIND_DISHWASHER in device.kinds
    ]
    if entities:
        async_add_entities(entities)


class FotileDishwasherPowerSwitch(FotileEntity, SwitchEntity):
    """Power switch backed by the App MQTT control channel."""

    _attr_icon = "mdi:power"

    def __init__(
        self,
        coordinator: FotileDataUpdateCoordinator,
        device: FotileDevice,
    ) -> None:
        super().__init__(coordinator, device, "dishwasher_power")
        self._attr_name = "电源"

    @property
    def is_on(self) -> bool | None:
        value = self._device.flat_status.get("AppState.PowerSwitchAll")
        if value is None:
            return None
        return to_bool(value)

    async def async_turn_on(self, **kwargs) -> None:
        await self.async_execute_command(
            self.coordinator.client.set_dishwasher_power(
                self._device.device_id,
                True,
            )
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.async_execute_command(
            self.coordinator.client.set_dishwasher_power(
                self._device.device_id,
                False,
            )
        )
        await self.coordinator.async_request_refresh()
