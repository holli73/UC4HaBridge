"""Fixtures: real VARA exports, Automic client mocked."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.automic_heating.const import (
    CONF_CLIENT,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_TOKEN_EXPIRES,
    CONF_TOKEN_NAME,
    CONF_VARA_SUMMARY,
    CONF_VARA_WEEKDAY,
    CONF_VARA_WEEKEND,
    DEFAULT_VARA_SUMMARY,
    DEFAULT_VARA_WEEKDAY,
    DEFAULT_VARA_WEEKEND,
    DOMAIN,
)
from custom_components.automic_heating.models import Vara

FIXTURES = Path(__file__).parent / "fixtures"
EXPORTS = {
    DEFAULT_VARA_SUMMARY: "summary.json",
    DEFAULT_VARA_WEEKDAY: "weekday.json",
    DEFAULT_VARA_WEEKEND: "weekend.json",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def load_vara(name: str) -> Vara:
    return Vara.from_export(name, json.loads((FIXTURES / EXPORTS[name]).read_text()))


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="http://uc4|1|summary",
        data={
            "url": "http://uc4.holli.at:8877",
            CONF_CLIENT: 1,
            "username": "HA/HEATING",
            CONF_VARA_SUMMARY: DEFAULT_VARA_SUMMARY,
            CONF_VARA_WEEKDAY: DEFAULT_VARA_WEEKDAY,
            CONF_VARA_WEEKEND: DEFAULT_VARA_WEEKEND,
            CONF_SCAN_INTERVAL: 15,
            CONF_TOKEN: "tok-1",
            CONF_TOKEN_NAME: "HA_BRIDGE_1",
            CONF_TOKEN_EXPIRES: "2099-01-01T00:00:00+00:00",
        },
    )


@pytest.fixture
def mock_client():
    with patch(
        "custom_components.automic_heating.AutomicClient", autospec=True
    ) as cls:
        client = cls.return_value
        client.get_vara = AsyncMock(side_effect=load_vara)
        client.put_var_col = AsyncMock()
        yield client
