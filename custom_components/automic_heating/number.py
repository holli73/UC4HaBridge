"""Day/Night temperatures for both schedules, mirrored 1:1 to the settings VARAs."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AutomicConfigEntry
from .const import COL_DAY, COL_NIGHT, MAX_TEMP, MIN_TEMP, SCHEDULE_WEEKDAY, SCHEDULE_WEEKEND, TEMP_STEP
from .coordinator import AutomicHeatingCoordinator
from .entity import AutomicRoomEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AutomicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        AutomicTemperatureNumber(coordinator, room, schedule, column)
        for room in coordinator.data.rooms
        for schedule in (SCHEDULE_WEEKDAY, SCHEDULE_WEEKEND)
        for column in (COL_DAY, COL_NIGHT)
    )


class AutomicTemperatureNumber(AutomicRoomEntity, NumberEntity):
    _entity_domain = "number"
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = MIN_TEMP
    _attr_native_max_value = MAX_TEMP
    _attr_native_step = TEMP_STEP
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: AutomicHeatingCoordinator, room: str, schedule: str, column: str
    ) -> None:
        key = f"{schedule}_{column.lower()}"
        days = "mon_fri" if schedule == SCHEDULE_WEEKDAY else "sat_sun"
        super().__init__(coordinator, room, key, f"{days}_{column.lower()}_temperature")
        self._attr_translation_key = key
        self._schedule = schedule
        self._column = column

    @property
    def native_value(self) -> float | None:
        return self.coordinator.settings(self._schedule).number(self.room, self._column)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_write(self._schedule, self.room, self._column, value)
