"""Options and reconfigure flows."""

from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.automic_heating.const import (
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_TOKEN_NAME,
    DEFAULT_VARA_SUMMARY,
    DEFAULT_VARA_WEEKDAY,
    DEFAULT_VARA_WEEKEND,
)

RECONFIGURE_INPUT = {
    "url": "http://automic.example:8088",
    "client": 1,
    "username": "HA/HEATING",
    "vara_summary": DEFAULT_VARA_SUMMARY,
    "vara_weekday": DEFAULT_VARA_WEEKDAY,
    "vara_weekend": DEFAULT_VARA_WEEKEND,
}


async def _setup(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def _reconfigure(hass, config_entry, user_input):
    result = await config_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


async def test_options_poll_interval(hass: HomeAssistant, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options[CONF_SCAN_INTERVAL] == 60
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.update_interval == timedelta(seconds=60)


async def test_reconfigure_keeps_token(hass, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    result = await _reconfigure(hass, config_entry, RECONFIGURE_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_TOKEN] == "tok-1"
    mock_client.create_token.assert_not_awaited()


async def test_reconfigure_url_change_needs_password(hass, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    result = await _reconfigure(hass, config_entry, {**RECONFIGURE_INPUT, "url": "http://new:8088"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "password_required"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**RECONFIGURE_INPUT, "url": "http://new:8088", "password": "pw"}
    )
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data["url"] == "http://new:8088"
    assert config_entry.data[CONF_TOKEN] == "tok-2"
    assert CONF_SCAN_INTERVAL in config_entry.data  # untouched keys survive
    mock_client.delete_token.assert_not_awaited()  # old token lives on the old server


async def test_reconfigure_new_token_same_server(hass, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    result = await _reconfigure(hass, config_entry, {**RECONFIGURE_INPUT, "password": "pw"})
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_TOKEN_NAME] == "HA_BRIDGE_2"
    mock_client.delete_token.assert_awaited_once_with("HA_BRIDGE_1")


async def test_reconfigure_bad_vara(hass, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    result = await _reconfigure(hass, config_entry, {**RECONFIGURE_INPUT, "vara_weekend": "NOPE"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_vara"}
