"""Tests for the config flow."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import patch

import probatio
import pytest
from homeassistant.config_entries import SOURCE_USER, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_HOST, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from sabatark import AgatarkError, derive_token

from custom_components.sabatark.config_flow import normalize_host
from custom_components.sabatark.const import (
    CONF_SESSION,
    CONF_SITE_ID,
    CONF_TOKEN,
    CONF_USER_ID,
    DOMAIN,
)

from .conftest import EMAIL, HOST, PASSWORD, SITE_ID, USER_ID, FakeController

USER_INPUT = {CONF_HOST: "192.0.2.10/", CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD}


async def _start(hass: HomeAssistant) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return result["flow_id"]


async def test_user_flow_creates_entry_for_chosen_site(
    hass: HomeAssistant, controller: FakeController
) -> None:
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "site"

    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_SITE_ID: str(SITE_ID)})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["result"].unique_id == f"{USER_ID}_{SITE_ID}"
    data = result["data"]
    assert data[CONF_HOST] == HOST
    assert data[CONF_EMAIL] == EMAIL
    assert data[CONF_TOKEN] == derive_token(PASSWORD, EMAIL)
    assert data[CONF_USER_ID] == USER_ID
    assert data[CONF_SITE_ID] == SITE_ID
    assert data[CONF_SESSION]["authorization"] == "session-1"
    assert PASSWORD not in str(data)
    assert controller.clients[0].closed is True
    assert controller.clients[0].logout_on_close is False


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (None, "invalid_auth"),
        (AgatarkError("HTTP 500", status=500), "cannot_connect"),
        (TimeoutError(), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, controller: FakeController, error: Exception | None, reason: str
) -> None:
    if error is None:
        controller.token = "another-token"
    else:
        controller.login_error = error
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": reason}

    controller.token = derive_token(PASSWORD, EMAIL)
    controller.login_error = None
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["step_id"] == "site"


async def test_user_flow_aborts_without_sites(
    hass: HomeAssistant, controller: FakeController
) -> None:
    controller.sites = []
    flow_id = await _start(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_sites"


async def test_user_flow_aborts_when_site_configured(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    flow_id = await _start(hass)
    await hass.config_entries.flow.async_configure(flow_id, USER_INPUT)
    result = await hass.config_entries.flow.async_configure(flow_id, {CONF_SITE_ID: str(SITE_ID)})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_stores_new_token(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    new_password = "battery staple"
    controller.token = derive_token(new_password, EMAIL)
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: new_password}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_TOKEN] == controller.token
    assert config_entry.data[CONF_SESSION]["authorization"] == "session-1"


async def test_reauth_rejects_other_account(
    hass: HomeAssistant, controller: FakeController, config_entry: MockConfigEntry
) -> None:
    controller.user_id = USER_ID + 1
    old_token = config_entry.data[CONF_TOKEN]
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: PASSWORD}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert config_entry.data[CONF_TOKEN] == old_token


async def test_access_options_flow(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("controller.local", "http://controller.local"),
        (" https://controller.local/ ", "https://controller.local"),
        ("http://192.0.2.10:8080", "http://192.0.2.10:8080"),
    ],
)
def test_normalize_host(host: str, expected: str) -> None:
    assert normalize_host(host) == expected


async def test_options_flow_module_is_used_when_present(
    hass: HomeAssistant, controller: FakeController, loaded_entry: MockConfigEntry
) -> None:
    class SabatarkOptionsFlow(OptionsFlow):
        async def async_step_init(self, user_input=None):
            return self.async_show_form(step_id="init", data_schema=probatio.Schema({}))

    module = ModuleType("custom_components.sabatark.options_flow")
    module.SabatarkOptionsFlow = SabatarkOptionsFlow
    with patch.dict(sys.modules, {module.__name__: module}):
        result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
