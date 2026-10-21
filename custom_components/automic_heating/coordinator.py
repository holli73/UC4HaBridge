"""Data coordinator: Automic is the single source of truth.

Every poll exports the three VARAs. AE 24.4 does not bump any object counter or
modified_date on :PUT_VAR, so change detection compares the parsed snapshot:
listeners are only notified when a value actually differs (always_update=False).
Every write is followed by an immediate re-read; HA never keeps its own state.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AutomicAuthError, AutomicClient, AutomicError, format_number
from .const import (
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES,
    CONF_TOKEN_NAME,
    CONF_TRIGGER_OBJECT,
    CONF_VARA_SUMMARY,
    CONF_VARA_WEEKDAY,
    CONF_VARA_WEEKEND,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRIGGER_OBJECT,
    DOMAIN,
    SCHEDULE_WEEKDAY,
    SCHEDULE_WEEKEND,
    TOKEN_LIFETIME,
    TOKEN_PREFIX,
    TOKEN_RENEW_BEFORE,
)
from .models import HeatingData, Vara

_LOGGER = logging.getLogger(__name__)


class AutomicHeatingCoordinator(DataUpdateCoordinator[HeatingData]):
    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: AutomicClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(
                    CONF_SCAN_INTERVAL,
                    entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                )
            ),
            always_update=False,
        )
        self.client = client
        self.vara_names = {
            "summary": entry.data[CONF_VARA_SUMMARY],
            SCHEDULE_WEEKDAY: entry.data[CONF_VARA_WEEKDAY],
            SCHEDULE_WEEKEND: entry.data[CONF_VARA_WEEKEND],
        }
        self._write_lock = asyncio.Lock()

    async def _async_update_data(self) -> HeatingData:
        try:
            summary, weekday, weekend = await asyncio.gather(
                self.client.get_vara(self.vara_names["summary"]),
                self.client.get_vara(self.vara_names[SCHEDULE_WEEKDAY]),
                self.client.get_vara(self.vara_names[SCHEDULE_WEEKEND]),
            )
        except AutomicAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AutomicError as err:
            raise UpdateFailed(str(err)) from err
        return HeatingData(summary, weekday, weekend)

    @property
    def trigger_object(self) -> str | None:
        """Object activated after every write (options override setup data).

        Never configured -> default object; explicitly cleared ("") -> none.
        """
        entry = self.config_entry
        value = entry.options.get(
            CONF_TRIGGER_OBJECT, entry.data.get(CONF_TRIGGER_OBJECT, DEFAULT_TRIGGER_OBJECT)
        )
        return value or None

    # ---- schedule helpers ------------------------------------------------

    @staticmethod
    def active_schedule(now: datetime | None = None) -> str:
        """Mon-Fri -> weekday VARA, Sat/Sun -> weekend VARA (HA local time)."""
        now = now or dt_util.now()
        return SCHEDULE_WEEKEND if now.weekday() >= 5 else SCHEDULE_WEEKDAY

    def settings(self, schedule: str) -> Vara:
        return self.data.weekend if schedule == SCHEDULE_WEEKEND else self.data.weekday

    # ---- writes ----------------------------------------------------------

    async def async_write(self, schedule: str, room: str, column: str, value: float | int) -> None:
        """Write one cell to the weekday/weekend VARA, then re-read Automic."""
        vara = self.settings(schedule)
        index = vara.columns.get(column)
        if index is None:
            raise HomeAssistantError(f"Column _{column} not found in {vara.name}")
        text = str(value) if isinstance(value, int) else format_number(value)
        async with self._write_lock:
            try:
                await self.client.put_var_col(vara.name, room, index, text, self.trigger_object)
            except AutomicAuthError as err:
                self.config_entry.async_start_reauth(self.hass)
                raise HomeAssistantError(str(err)) from err
            except AutomicError as err:
                raise HomeAssistantError(f"Automic write failed: {err}") from err
            _LOGGER.debug(
                "Wrote %s/%s/_%s = %s (trigger: %s)",
                vara.name, room, column, text, self.trigger_object,
            )
        await self.async_refresh()

    # ---- token renewal ---------------------------------------------------

    async def async_renew_token_if_needed(self, *_: object) -> None:
        """Create a successor token with the current one, then drop the old one."""
        expires = dt_util.parse_datetime(self.config_entry.data[CONF_TOKEN_EXPIRES])
        if expires and expires - dt_util.utcnow() > TOKEN_RENEW_BEFORE:
            return
        old_name = self.config_entry.data[CONF_TOKEN_NAME]
        try:
            token = await self.client.create_token(TOKEN_LIFETIME, TOKEN_PREFIX)
        except AutomicAuthError:
            self.config_entry.async_start_reauth(self.hass)
            return
        except AutomicError as err:
            _LOGGER.warning("Token renewal failed, will retry: %s", err)
            return
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={
                **self.config_entry.data,
                CONF_TOKEN: token.value,
                CONF_TOKEN_NAME: token.name,
                CONF_TOKEN_EXPIRES: token.expires.isoformat(),
            },
        )
        _LOGGER.info("Renewed Automic API token, valid until %s", token.expires)
        try:
            await self.client.delete_token(old_name)
        except AutomicError as err:
            _LOGGER.warning("Could not delete old token %s: %s", old_name, err)
