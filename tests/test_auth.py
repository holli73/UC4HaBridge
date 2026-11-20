"""Token handling: the stored password lets the bridge log in again by itself."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.automic_heating.api import AutomicAuthError, AutomicClient, Token
from custom_components.automic_heating.const import (
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES,
    CONF_TOKEN_NAME,
    DEFAULT_VARA_SUMMARY,
)

NEW = Token("HA_BRIDGE_2", "tok-2", datetime(2099, 6, 1, tzinfo=timezone.utc))


def _client(password: str | None = "pw") -> AutomicClient:
    client = AutomicClient(MagicMock(), "http://x", 1, "HA/HEATING", "tok-1", password)
    client.on_new_token = MagicMock()

    async def create_token(lifetime, prefix, password=None):
        assert password == "pw"
        client._token = NEW.value
        return NEW

    client.create_token = AsyncMock(side_effect=create_token)
    return client


def _send_rejecting(client: AutomicClient):
    """Fake transport: only the new token is accepted."""

    async def send(method, path, **kwargs):
        await asyncio.sleep(0)
        if client.token != NEW.value:
            raise AutomicAuthError("unauthorized")
        return {"ok": path}

    return AsyncMock(side_effect=send)


async def test_rejected_token_relogin_and_retry() -> None:
    client = _client()
    client._send = _send_rejecting(client)
    assert await client._request("GET", "/a") == {"ok": "/a"}
    client.create_token.assert_awaited_once()
    client.on_new_token.assert_called_once_with(NEW)


async def test_concurrent_rejections_login_once() -> None:
    client = _client()
    client._send = _send_rejecting(client)
    results = await asyncio.gather(*(client._request("GET", f"/{i}") for i in range(4)))
    assert [r["ok"] for r in results] == ["/0", "/1", "/2", "/3"]
    client.create_token.assert_awaited_once()


async def test_no_password_raises() -> None:
    client = _client(password=None)
    client._send = _send_rejecting(client)
    try:
        await client._request("GET", "/a")
    except AutomicAuthError:
        pass
    else:
        raise AssertionError("expected AutomicAuthError")
    client.create_token.assert_not_awaited()


async def _setup(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_new_token_is_persisted(hass: HomeAssistant, config_entry, mock_client) -> None:
    await _setup(hass, config_entry)
    config_entry.runtime_data._handle_new_token(NEW)
    await hass.async_block_till_done()
    assert config_entry.data[CONF_TOKEN] == "tok-2"
    assert config_entry.data[CONF_TOKEN_NAME] == "HA_BRIDGE_2"
    mock_client.delete_token.assert_awaited_once_with("HA_BRIDGE_1")


async def test_expiring_token_renewed_at_setup(hass, config_entry, mock_client) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_TOKEN_EXPIRES: "2000-01-01T00:00:00+00:00"}
    )
    mock_client.renew_token = AsyncMock()
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    mock_client.renew_token.assert_awaited_once()
    assert not hass.config_entries.flow.async_progress()


async def test_old_entry_asks_password_once(hass, config_entry, mock_client) -> None:
    """Entries without a stored password start reauth; reauth stores it."""
    data = {k: v for k, v in config_entry.data.items() if k != "password"}
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, data=data)
    mock_client.can_login = False
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]

    result = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {"password": "pw"})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["password"] == "pw"
    assert config_entry.data[CONF_TOKEN] == "tok-2"
    mock_client.get_vara.assert_any_await(DEFAULT_VARA_SUMMARY)
