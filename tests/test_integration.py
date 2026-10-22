"""Entity mapping and write-back tests."""

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.automic_heating.const import (
    DEFAULT_TRIGGER_OBJECT as TRIGGER,
    DEFAULT_VARA_DAY_NIGHT,
    DEFAULT_VARA_WEEKDAY,
    DEFAULT_VARA_WEEKEND,
)
from custom_components.automic_heating.models import Vara

from .conftest import load_vara

CLIMATE = "climate.uc4_clauderoomtest"


def _day_night(day: str = "04", night: str = "22", summer: str = "No") -> Vara:
    vara = load_vara(DEFAULT_VARA_DAY_NIGHT)
    rows = {"DayTimeStart": (day,), "NightTimeStart": (night,), "IsSummer": (summer,)}
    return Vara(vara.name, vara.columns, rows)


def _serve(mock_client, day_night: Vara) -> None:
    mock_client.get_vara.side_effect = (
        lambda name: day_night if name == DEFAULT_VARA_DAY_NIGHT else load_vara(name)
    )


async def _setup(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.freeze_time("2026-10-21 18:00:00+00:00")  # Wednesday 11:00 local (US/Pacific): day
async def test_climate_weekday(hass: HomeAssistant, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    state = hass.states.get(CLIMATE)
    assert state.state == HVACMode.HEAT
    assert state.attributes["current_temperature"] == 23.0  # SUMMARY _actTemp
    assert state.attributes["temperature"] == 22.0  # weekday _Day
    assert state.attributes["preset_mode"] == "manual"  # _Mode 4
    assert state.attributes["hvac_action"] == HVACAction.IDLE  # infra/floor Off
    assert state.attributes["must_temperature"] == 22.0  # "00000000022.0000..."
    assert state.attributes["active_schedule"] == "weekday"
    assert state.attributes["friendly_name"] == "ClaudeRoomTest"  # display name unchanged
    # Only rooms from the settings VARA, no sensor-only rows.
    assert hass.states.get("climate.uc4_boiler") is None
    assert hass.states.get("climate.uc4_bad") is not None


@pytest.mark.freeze_time("2026-10-21 18:00:00+00:00")
async def test_set_temperature_weekday(hass, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 21.5}, blocking=True
    )
    mock_client.put_var_col.assert_awaited_once_with(DEFAULT_VARA_WEEKDAY, "ClaudeRoomTest", 1, "21.5", TRIGGER)


@pytest.mark.freeze_time("2026-10-24 18:00:00+00:00")  # Saturday
async def test_set_temperature_weekend(hass, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 23}, blocking=True
    )
    mock_client.put_var_col.assert_awaited_once_with(DEFAULT_VARA_WEEKEND, "ClaudeRoomTest", 1, "23", TRIGGER)


@pytest.mark.freeze_time("2026-10-21 18:00:00+00:00")
async def test_hvac_and_preset(hass, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": CLIMATE, "hvac_mode": "off"}, blocking=True
    )
    mock_client.put_var_col.assert_awaited_with(DEFAULT_VARA_WEEKDAY, "ClaudeRoomTest", 3, "0", TRIGGER)
    await hass.services.async_call(
        "climate", "set_preset_mode", {"entity_id": CLIMATE, "preset_mode": "both"}, blocking=True
    )
    mock_client.put_var_col.assert_awaited_with(DEFAULT_VARA_WEEKDAY, "ClaudeRoomTest", 3, "3", TRIGGER)


@pytest.mark.freeze_time("2026-10-21 18:00:00+00:00")
async def test_number_and_select(hass, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    assert hass.states.get("number.uc4_clauderoomtest_sat_sun_night_temperature").state == "20.0"
    assert hass.states.get("select.uc4_clauderoomtest_mon_fri_heating_mode").state == "manual"
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.uc4_clauderoomtest_sat_sun_night_temperature", "value": 18},
        blocking=True,
    )
    mock_client.put_var_col.assert_awaited_with(DEFAULT_VARA_WEEKEND, "ClaudeRoomTest", 2, "18", TRIGGER)
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.uc4_clauderoomtest_mon_fri_heating_mode", "option": "floor"},
        blocking=True,
    )
    mock_client.put_var_col.assert_awaited_with(DEFAULT_VARA_WEEKDAY, "ClaudeRoomTest", 3, "2", TRIGGER)


@pytest.mark.freeze_time("2026-10-21 18:00:00+00:00")
async def test_change_in_automic_reaches_ha(hass, config_entry, mock_client) -> None:
    """A value changed in Automic shows up in HA on the next scheduled poll."""
    await _setup(hass, config_entry)
    changed = load_vara(DEFAULT_VARA_WEEKDAY)
    rows = dict(changed.rows)
    rows["ClaudeRoomTest"] = ("19.5",) + rows["ClaudeRoomTest"][1:]
    changed = Vara(changed.name, changed.columns, rows)
    mock_client.get_vara.side_effect = (
        lambda name: changed if name == DEFAULT_VARA_WEEKDAY else load_vara(name)
    )

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=16))
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(CLIMATE).attributes["temperature"] == 19.5


@pytest.mark.freeze_time("2026-10-21 18:00:00+00:00")
async def test_turn_on_room_without_floor_heating(hass, config_entry, mock_client) -> None:
    """KellerLift: mode 0 on both schedules, SUMMARY _FloorHeating = NoHeating -> infra."""
    await _setup(hass, config_entry)
    state = hass.states.get("climate.uc4_kellerlift")
    assert state.state == HVACMode.OFF
    assert state.attributes["preset_modes"] == ["infra", "manual"]
    await hass.services.async_call(
        "climate", "turn_on", {"entity_id": "climate.uc4_kellerlift"}, blocking=True
    )
    mock_client.put_var_col.assert_awaited_once_with(
        DEFAULT_VARA_WEEKDAY, "KellerLift", 3, "1", TRIGGER
    )


@pytest.mark.freeze_time("2026-10-21 18:00:00+00:00")
async def test_turn_on_room_with_both(hass, config_entry, mock_client) -> None:
    """Speis: weekday mode 0, weekend mode 0, no NoHeating marker -> floor."""
    await _setup(hass, config_entry)
    assert hass.states.get("climate.uc4_speis").attributes["preset_modes"] == [
        "infra", "floor", "both", "manual"
    ]
    await hass.services.async_call(
        "climate", "turn_on", {"entity_id": "climate.uc4_speis"}, blocking=True
    )
    mock_client.put_var_col.assert_awaited_once_with(DEFAULT_VARA_WEEKDAY, "Speis", 3, "2", TRIGGER)


async def test_remove_device_only_when_room_is_gone(hass, config_entry, mock_client) -> None:
    from homeassistant.helpers import device_registry as dr
    from custom_components.automic_heating import async_remove_config_entry_device

    await _setup(hass, config_entry)
    registry = dr.async_get(hass)
    device = registry.async_get_device({("automic_heating", f"{config_entry.unique_id}|ClaudeRoomTest")})
    assert device is not None
    assert not await async_remove_config_entry_device(hass, config_entry, device)

    # Room removed from the settings VARA in Automic.
    weekday = load_vara(DEFAULT_VARA_WEEKDAY)
    rows = {k: v for k, v in weekday.rows.items() if k != "ClaudeRoomTest"}
    reduced = Vara(weekday.name, weekday.columns, rows)
    mock_client.get_vara.side_effect = (
        lambda name: reduced if name == DEFAULT_VARA_WEEKDAY else load_vara(name)
    )
    await config_entry.runtime_data.async_refresh()
    assert hass.states.get(CLIMATE).state == "unavailable"
    assert await async_remove_config_entry_device(hass, config_entry, device)


@pytest.mark.freeze_time("2026-10-22 06:00:00+00:00")  # Wednesday 23:00 local: night
async def test_night_uses_night_column(hass, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    state = hass.states.get(CLIMATE)
    assert state.attributes["temperature"] == 20.0  # weekday _Night
    assert state.attributes["active_period"] == "night"
    assert state.attributes["day_temperature"] == 22.0
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 19}, blocking=True
    )
    mock_client.put_var_col.assert_awaited_once_with(DEFAULT_VARA_WEEKDAY, "ClaudeRoomTest", 2, "19", TRIGGER)


async def test_period_flips_at_night_start(hass, config_entry, mock_client, freezer) -> None:
    freezer.move_to("2026-10-22 04:59:00+00:00")  # Wednesday 21:59 local
    await _setup(hass, config_entry)
    assert hass.states.get(CLIMATE).attributes["temperature"] == 22.0
    freezer.move_to("2026-10-22 05:00:01+00:00")  # 22:00:01 local
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(CLIMATE).attributes["temperature"] == 20.0


@pytest.mark.parametrize(
    ("day", "night", "local_hour", "period"),
    [
        ("04", "22", 4, "day"),
        ("04", "22", 3, "night"),
        ("04", "22", 22, "night"),
        ("22", "04", 23, "day"),  # window over midnight
        ("22", "04", 10, "night"),
        ("", "22", 3, "day"),  # unreadable -> day
    ],
)
async def test_active_period(hass, config_entry, mock_client, day, night, local_hour, period) -> None:
    _serve(mock_client, _day_night(day, night))
    await _setup(hass, config_entry)
    now = dt_util.now().replace(hour=local_hour, minute=30)
    assert config_entry.runtime_data.active_period(now) == period


@pytest.mark.freeze_time("2026-10-21 18:00:00+00:00")
async def test_summer_disables_heating(hass, config_entry, mock_client) -> None:
    _serve(mock_client, _day_night(summer="Yes"))
    await _setup(hass, config_entry)
    state = hass.states.get(CLIMATE)
    assert state.state == HVACMode.OFF  # _Mode is 4 (manual)
    assert state.attributes["hvac_action"] == HVACAction.OFF
    assert state.attributes["summer"] is True
    for service, data in (
        ("turn_on", {}),
        ("set_temperature", {"temperature": 21}),
        ("set_preset_mode", {"preset_mode": "floor"}),
    ):
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                "climate", service, {"entity_id": CLIMATE, **data}, blocking=True
            )
    # Off keeps _Mode for when summer ends.
    await hass.services.async_call("climate", "turn_off", {"entity_id": CLIMATE}, blocking=True)
    mock_client.put_var_col.assert_not_awaited()
    # Schedule settings stay editable.
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.uc4_clauderoomtest_mon_fri_day_temperature", "value": 21},
        blocking=True,
    )
    mock_client.put_var_col.assert_awaited_once_with(DEFAULT_VARA_WEEKDAY, "ClaudeRoomTest", 1, "21", TRIGGER)
