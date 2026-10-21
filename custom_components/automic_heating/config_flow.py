"""Config flow. The password is only used to create an API token and is never stored."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AutomicAuthError, AutomicClient, AutomicError
from .const import (
    CONF_CLIENT,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES,
    CONF_TOKEN_NAME,
    CONF_TRIGGER_OBJECT,
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

SCAN_INTERVAL_VALIDATOR = vol.All(vol.Coerce(int), vol.Range(min=5, max=3600))

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL, default=DEFAULT_URL): str,
        vol.Required(CONF_CLIENT, default=DEFAULT_CLIENT): vol.Coerce(int),
        vol.Required(CONF_USERNAME, default="HA/HEATING"): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_VARA_SUMMARY, default=DEFAULT_VARA_SUMMARY): str,
        vol.Required(CONF_VARA_WEEKDAY, default=DEFAULT_VARA_WEEKDAY): str,
        vol.Required(CONF_VARA_WEEKEND, default=DEFAULT_VARA_WEEKEND): str,
        vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): SCAN_INTERVAL_VALIDATOR,
        vol.Optional(CONF_TRIGGER_OBJECT): str,
    }
)

OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SCAN_INTERVAL): SCAN_INTERVAL_VALIDATOR,
        vol.Optional(CONF_TRIGGER_OBJECT): str,
    }
)

# Connection settings that require a new token when changed.
CONNECTION_KEYS = (CONF_URL, CONF_CLIENT, CONF_USERNAME)

RECONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Required(CONF_CLIENT): vol.Coerce(int),
        vol.Required(CONF_USERNAME): str,
        vol.Optional(CONF_PASSWORD): str,
        vol.Required(CONF_VARA_SUMMARY): str,
        vol.Required(CONF_VARA_WEEKDAY): str,
        vol.Required(CONF_VARA_WEEKEND): str,
    }
)


class AutomicHeatingConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _async_validate(
        self, data: Mapping[str, Any], password: str | None, token: str | None = None
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """Check the VARAs are readable; with a password, create a new token first.

        Returns the token fields to store (empty when the existing token is kept)
        or errors.
        """
        client = AutomicClient(
            async_get_clientsession(self.hass),
            data[CONF_URL],
            data[CONF_CLIENT],
            data[CONF_USERNAME],
            token,
        )
        new_token = None
        if password:
            try:
                new_token = await client.create_token(TOKEN_LIFETIME, TOKEN_PREFIX, password)
            except AutomicAuthError:
                return {}, {"base": "invalid_auth"}
            except AutomicError:
                return {}, {"base": "cannot_connect"}
        try:
            for key in (CONF_VARA_SUMMARY, CONF_VARA_WEEKDAY, CONF_VARA_WEEKEND):
                await client.get_vara(data[key])
        except AutomicAuthError:
            return {}, {"base": "invalid_auth"}
        except (AutomicError, KeyError, ValueError):
            if new_token:
                await client.delete_token(new_token.name)
            return {}, {"base": "invalid_vara"}
        if (trigger := data.get(CONF_TRIGGER_OBJECT)) and not await client.object_exists(trigger):
            if new_token:
                await client.delete_token(new_token.name)
            return {}, {"base": "trigger_not_found"}
        if new_token is None:
            return {}, {}
        return {
            CONF_TOKEN: new_token.value,
            CONF_TOKEN_NAME: new_token.name,
            CONF_TOKEN_EXPIRES: new_token.expires.isoformat(),
        }, {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AutomicHeatingOptionsFlow:
        return AutomicHeatingOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_URL].rstrip('/')}|{user_input[CONF_CLIENT]}"
                f"|{user_input[CONF_VARA_SUMMARY]}"
            )
            self._abort_if_unique_id_configured()
            password = user_input.pop(CONF_PASSWORD)
            _normalize_trigger(user_input)
            token_data, errors = await self._async_validate(user_input, password)
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
            token_data, errors = await self._async_validate(
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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change URL, client, user or VARA names of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            password = user_input.pop(CONF_PASSWORD, None)
            connection_changed = any(
                user_input[key] != entry.data[key] for key in CONNECTION_KEYS
            )
            if connection_changed and not password:
                errors["base"] = "password_required"
            else:
                token_data, errors = await self._async_validate(
                    user_input, password, None if password else entry.data[CONF_TOKEN]
                )
                if not errors:
                    if token_data and not connection_changed:
                        # Same server/user: drop the token that was just replaced.
                        client = AutomicClient(
                            async_get_clientsession(self.hass),
                            user_input[CONF_URL],
                            user_input[CONF_CLIENT],
                            user_input[CONF_USERNAME],
                            token_data[CONF_TOKEN],
                        )
                        try:
                            await client.delete_token(entry.data[CONF_TOKEN_NAME])
                        except AutomicError:
                            pass
                    return self.async_update_reload_and_abort(
                        entry,
                        title=f"Automic heating (client {user_input[CONF_CLIENT]})",
                        data_updates={**user_input, **token_data},
                    )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                RECONFIGURE_SCHEMA, user_input or entry.data
            ),
            errors=errors,
        )


class AutomicHeatingOptionsFlow(OptionsFlowWithReload):
    """Runtime options; saving reloads the entry."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            _normalize_trigger(user_input)
            trigger = user_input[CONF_TRIGGER_OBJECT]
            try:
                exists = not trigger or await entry.runtime_data.client.object_exists(trigger)
            except AutomicError:
                errors["base"] = "cannot_connect"
            else:
                if exists:
                    return self.async_create_entry(data=user_input)
                errors["base"] = "trigger_not_found"
        current = {
            CONF_SCAN_INTERVAL: entry.options.get(
                CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            CONF_TRIGGER_OBJECT: entry.options.get(
                CONF_TRIGGER_OBJECT, entry.data.get(CONF_TRIGGER_OBJECT, "")
            ),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                OPTIONS_SCHEMA, user_input or current
            ),
            errors=errors,
        )


def _normalize_trigger(user_input: dict[str, Any]) -> None:
    """Automic object names are upper case; empty means no trigger."""
    user_input[CONF_TRIGGER_OBJECT] = (user_input.get(CONF_TRIGGER_OBJECT) or "").strip().upper()
