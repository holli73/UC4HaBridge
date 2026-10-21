"""Automic Heating: two-way sync of room heating between Automic and Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.event import async_track_time_interval

from .api import AutomicClient
from .const import CONF_CLIENT, CONF_TOKEN, DOMAIN, TOKEN_CHECK_INTERVAL
from .coordinator import AutomicHeatingCoordinator

PLATFORMS = [Platform.CLIMATE, Platform.NUMBER, Platform.SELECT]

type AutomicConfigEntry = ConfigEntry[AutomicHeatingCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: AutomicConfigEntry) -> bool:
    client = AutomicClient(
        async_get_clientsession(hass),
        entry.data[CONF_URL],
        entry.data[CONF_CLIENT],
        entry.data[CONF_USERNAME],
        entry.data[CONF_TOKEN],
    )
    coordinator = AutomicHeatingCoordinator(hass, entry, client)
    await coordinator.async_renew_token_if_needed()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    entry.async_on_unload(
        async_track_time_interval(
            hass, coordinator.async_renew_token_if_needed, TOKEN_CHECK_INTERVAL
        )
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AutomicConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: AutomicConfigEntry, device: DeviceEntry
) -> bool:
    """Allow deleting a room device only if the room is gone from the settings VARA."""
    rooms = set(entry.runtime_data.data.rooms)
    return not any(
        domain == DOMAIN and identifier.rsplit("|", 1)[-1] in rooms
        for domain, identifier in device.identifiers
    )
