"""Heating mode per schedule (_Mode column), mirrored 1:1 to the settings VARAs."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AutomicConfigEntry
from .const import COL_MODE, MODE_IDS, MODES, SCHEDULE_WEEKDAY, SCHEDULE_WEEKEND
from .coordinator import AutomicHeatingCoordinator
from .entity import AutomicRoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AutomicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        AutomicModeSelect(coordinator, room, schedule)
        for room in coordinator.data.rooms
        for schedule in (SCHEDULE_WEEKDAY, SCHEDULE_WEEKEND)
    )


class AutomicModeSelect(AutomicRoomEntity, SelectEntity):
    _entity_domain = "select"
    _attr_options = list(MODES.values())
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: AutomicHeatingCoordinator, room: str, schedule: str) -> None:
        key = f"{schedule}_mode"
        days = "mon_fri" if schedule == SCHEDULE_WEEKDAY else "sat_sun"
        super().__init__(coordinator, room, key, f"{days}_heating_mode")
        self._attr_translation_key = key
        self._schedule = schedule

    @property
    def current_option(self) -> str | None:
        return MODES.get(self.coordinator.settings(self._schedule).integer(self.room, COL_MODE))

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_write(self._schedule, self.room, COL_MODE, MODE_IDS[option])
