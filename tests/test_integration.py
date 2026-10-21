"""Entity mapping and write-back tests."""

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.automic_heating.const import (
    DEFAULT_VARA_WEEKDAY,
    DEFAULT_VARA_WEEKEND,
)
from custom_components.automic_heating.models import Vara

from .conftest import load_vara

CLIMATE = "climate.uc4_clauderoomtest"


async def _setup(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.freeze_time("2026-10-21 10:00:00+00:00")  # Wednesday
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


@pytest.mark.freeze_time("2026-10-21 10:00:00+00:00")
async def test_set_temperature_weekday(hass, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 21.5}, blocking=True
    )
    mock_client.put_var_col.assert_awaited_once_with(DEFAULT_VARA_WEEKDAY, "ClaudeRoomTest", 1, "21.5")


@pytest.mark.freeze_time("2026-10-24 10:00:00+00:00")  # Saturday
async def test_set_temperature_weekend(hass, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    await hass.services.async_call(
        "climate", "set_temperature", {"entity_id": CLIMATE, "temperature": 23}, blocking=True
    )
    mock_client.put_var_col.assert_awaited_once_with(DEFAULT_VARA_WEEKEND, "ClaudeRoomTest", 1, "23")


@pytest.mark.freeze_time("2026-10-21 10:00:00+00:00")
async def test_hvac_and_preset(hass, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    await hass.services.async_call(
        "climate", "set_hvac_mode", {"entity_id": CLIMATE, "hvac_mode": "off"}, blocking=True
    )
    mock_client.put_var_col.assert_awaited_with(DEFAULT_VARA_WEEKDAY, "ClaudeRoomTest", 3, "0")
    await hass.services.async_call(
        "climate", "set_preset_mode", {"entity_id": CLIMATE, "preset_mode": "both"}, blocking=True
    )
    mock_client.put_var_col.assert_awaited_with(DEFAULT_VARA_WEEKDAY, "ClaudeRoomTest", 3, "3")


@pytest.mark.freeze_time("2026-10-21 10:00:00+00:00")
async def test_number_and_select(hass, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    assert hass.states.get("number.uc4_clauderoomtest_sat_sun_night_temperature").state == "20.0"
    assert hass.states.get("select.uc4_clauderoomtest_mon_fri_heating_mode").state == "manual"
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.uc4_clauderoomtest_sat_sun_night_temperature", "value": 18},
        blocking=True,
    )
    mock_client.put_var_col.assert_awaited_with(DEFAULT_VARA_WEEKEND, "ClaudeRoomTest", 2, "18")
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.uc4_clauderoomtest_mon_fri_heating_mode", "option": "floor"},
        blocking=True,
    )
    mock_client.put_var_col.assert_awaited_with(DEFAULT_VARA_WEEKDAY, "ClaudeRoomTest", 3, "2")


@pytest.mark.freeze_time("2026-10-21 10:00:00+00:00")
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
