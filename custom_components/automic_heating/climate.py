"""Room thermostats.

current temperature  <- SUMMARY _actTemp
target temperature   <-> _Day of today's settings VARA (Mon-Fri weekday, Sat/Sun weekend)
hvac mode / preset   <-> _Mode of today's settings VARA (0=off, 1..4 = presets)
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change

from . import AutomicConfigEntry
from .const import (
    COL_ACT_TEMP,
    COL_DAY,
    COL_FLOOR,
    COL_HEATING_MODE,
    COL_INFRA,
    COL_MODE,
    COL_MUST_TEMP,
    COL_NIGHT,
    MAX_TEMP,
    MIN_TEMP,
    MODE_IDS,
    MODES,
    SCHEDULE_WEEKDAY,
    SCHEDULE_WEEKEND,
    TEMP_STEP,
)
from .coordinator import AutomicHeatingCoordinator
from .entity import AutomicRoomEntity

PRESETS = [name for mode_id, name in MODES.items() if mode_id != 0]
NO_HEATING = "noheating"  # SUMMARY value for a heating type the room does not have


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AutomicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(AutomicRoomClimate(coordinator, room) for room in coordinator.data.rooms)


class AutomicRoomClimate(AutomicRoomEntity, ClimateEntity):
    _entity_domain = "climate"
    _attr_name = None
    _attr_translation_key = "room"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = TEMP_STEP
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: AutomicHeatingCoordinator, room: str) -> None:
        super().__init__(coordinator, room, "climate")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # The active schedule flips at midnight without any VARA change.
        self.async_on_remove(
            async_track_time_change(self.hass, self._midnight, hour=0, minute=0, second=1)
        )

    @callback
    def _midnight(self, _now: object) -> None:
        self.async_write_ha_state()

    @property
    def _schedule(self) -> str:
        return self.coordinator.active_schedule()

    @property
    def _mode(self) -> int | None:
        return self.coordinator.settings(self._schedule).integer(self.room, COL_MODE)

    def _has(self, column: str) -> bool:
        """False only if SUMMARY explicitly says the room has no such heating."""
        value = self.coordinator.data.summary.raw(self.room, column) or ""
        return value.lower() != NO_HEATING

    def _mode_supported(self, mode: int) -> bool:
        infra, floor = self._has(COL_INFRA), self._has(COL_FLOOR)
        return {MODE_IDS["infra"]: infra, MODE_IDS["floor"]: floor, MODE_IDS["both"]: infra and floor}.get(
            mode, True
        )

    @property
    def preset_modes(self) -> list[str]:
        """Only heating types the room actually has (plus the current one)."""
        current = self.preset_mode
        return [p for p in PRESETS if self._mode_supported(MODE_IDS[p]) or p == current]

    @property
    def current_temperature(self) -> float | None:
        return self.coordinator.data.summary.number(self.room, COL_ACT_TEMP)

    @property
    def target_temperature(self) -> float | None:
        return self.coordinator.settings(self._schedule).number(self.room, COL_DAY)

    @property
    def hvac_mode(self) -> HVACMode | None:
        mode = self._mode
        if mode is None:
            return None
        return HVACMode.OFF if mode == 0 else HVACMode.HEAT

    @property
    def preset_mode(self) -> str | None:
        mode = self._mode
        return MODES.get(mode) if mode else None

    @property
    def hvac_action(self) -> HVACAction | None:
        if self._mode == 0:
            return HVACAction.OFF
        summary = self.coordinator.data.summary
        heating = "on" in (
            (summary.raw(self.room, COL_INFRA) or "").lower(),
            (summary.raw(self.room, COL_FLOOR) or "").lower(),
        )
        return HVACAction.HEATING if heating else HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        summary = self.coordinator.data.summary
        settings = self.coordinator.settings(self._schedule)
        return {
            "active_schedule": self._schedule,
            "must_temperature": summary.number(self.room, COL_MUST_TEMP),
            "night_temperature": settings.number(self.room, COL_NIGHT),
            "automic_heating_mode": summary.integer(self.room, COL_HEATING_MODE),
            "infra_heating": summary.raw(self.room, COL_INFRA),
            "floor_heating": summary.raw(self.room, COL_FLOOR),
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            await self.coordinator.async_write(
                self._schedule, self.room, COL_DAY, float(temperature)
            )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self.coordinator.async_write(
            self._schedule, self.room, COL_MODE, MODE_IDS[preset_mode]
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            mode = 0
        elif self._mode:
            return  # already heating
        else:
            mode = self._turn_on_mode()
        await self.coordinator.async_write(self._schedule, self.room, COL_MODE, mode)

    def _turn_on_mode(self) -> int:
        """Re-use the other schedule's mode if the room supports it, else the
        heating the room has: floor, then infra, then manual."""
        other = SCHEDULE_WEEKEND if self._schedule == SCHEDULE_WEEKDAY else SCHEDULE_WEEKDAY
        other_mode = self.coordinator.settings(other).integer(self.room, COL_MODE)
        if other_mode and self._mode_supported(other_mode):
            return other_mode
        for name in ("floor", "infra"):
            if self._mode_supported(MODE_IDS[name]):
                return MODE_IDS[name]
        return MODE_IDS["manual"]

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
