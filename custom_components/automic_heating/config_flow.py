"""Config flow. The password is only used to create an API token and is never stored."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AutomicAuthError, AutomicClient, AutomicError
from .const import (
    CONF_CLIENT,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES,
    CONF_TOKEN_NAME,
    CONF_VARA_SUMMARY,
    CONF_VARA_WEEKDAY,
    CONF_VARA_WEEKEND,
    DEFAULT_CLIENT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_URL,
    DEFAULT_VARA_SUMMARY,
    DEFAULT_VARA_WEEKDAY,
    DEFAULT_VARA_WEEKEND,
    DOMAIN,
    TOKEN_LIFETIME,
    TOKEN_PREFIX,
)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL, default=DEFAULT_URL): str,
        vol.Required(CONF_CLIENT, default=DEFAULT_CLIENT): vol.Coerce(int),
        vol.Required(CONF_USERNAME, default="HA/HEATING"): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_VARA_SUMMARY, default=DEFAULT_VARA_SUMMARY): str,
        vol.Required(CONF_VARA_WEEKDAY, default=DEFAULT_VARA_WEEKDAY): str,
        vol.Required(CONF_VARA_WEEKEND, default=DEFAULT_VARA_WEEKEND): str,
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=5, max=3600)
        ),
    }
)


class AutomicHeatingConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _async_create_token(
        self, data: Mapping[str, Any], password: str
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Validate credentials + VARAs; return token fields or errors."""
        client = AutomicClient(
            async_get_clientsession(self.hass),
            data[CONF_URL],
            data[CONF_CLIENT],
            data[CONF_USERNAME],
        )
        try:
            token = await client.create_token(TOKEN_LIFETIME, TOKEN_PREFIX, password)
        except AutomicAuthError:
            return {}, {"base": "invalid_auth"}
        except AutomicError:
            return {}, {"base": "cannot_connect"}
        try:
            for key in (CONF_VARA_SUMMARY, CONF_VARA_WEEKDAY, CONF_VARA_WEEKEND):
                await client.get_vara(data[key])
        except (AutomicError, KeyError, ValueError):
            await client.delete_token(token.name)
            return {}, {"base": "invalid_vara"}
        return {
            CONF_TOKEN: token.value,
            CONF_TOKEN_NAME: token.name,
            CONF_TOKEN_EXPIRES: token.expires.isoformat(),
        }, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_URL].rstrip('/')}|{user_input[CONF_CLIENT]}"
                f"|{user_input[CONF_VARA_SUMMARY]}"
            )
            self._abort_if_unique_id_configured()
            password = user_input.pop(CONF_PASSWORD)
            token_data, errors = await self._async_create_token(user_input, password)
            if not errors:
                return self.async_create_entry(
                    title=f"Automic heating (client {user_input[CONF_CLIENT]})",
                    data={**user_input, **token_data},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            token_data, errors = await self._async_create_token(
                entry.data, user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, **token_data}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )
