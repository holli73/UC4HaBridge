"""Base entity: one HA device per room."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AutomicHeatingCoordinator


class AutomicRoomEntity(CoordinatorEntity[AutomicHeatingCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AutomicHeatingCoordinator, room: str, key: str) -> None:
        super().__init__(coordinator)
        self.room = room
        base = coordinator.config_entry.unique_id or coordinator.config_entry.entry_id
        self._attr_unique_id = f"{base}|{room}|{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{base}|{room}")},
            name=room,
            manufacturer="Automic",
            model="Heating room",
        )

    @property
    def available(self) -> bool:
        return super().available and self.room in self.coordinator.data.weekday.rows
