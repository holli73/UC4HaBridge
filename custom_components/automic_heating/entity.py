"""Base entity: one HA device per room."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN, ENTITY_ID_PREFIX
from .coordinator import AutomicHeatingCoordinator


class AutomicRoomEntity(CoordinatorEntity[AutomicHeatingCoordinator]):
    _attr_has_entity_name = True
    _entity_domain: str  # set by each platform, e.g. "climate"

    def __init__(
        self,
        coordinator: AutomicHeatingCoordinator,
        room: str,
        key: str,
        object_suffix: str = "",
    ) -> None:
        super().__init__(coordinator)
        self.room = room
        # Requested entity id, e.g. climate.uc4_bad / number.uc4_bad_mon_fri_day_temperature.
        # Only applies on first registration; users can still rename in the UI.
        object_id = slugify(f"{ENTITY_ID_PREFIX}_{room}_{object_suffix}".rstrip("_"))
        self.entity_id = f"{self._entity_domain}.{object_id}"
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
