"""Config flow for the Sabatark integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
import probatio
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_HOST, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from sabatark import AgatarkClient, AgatarkError, AuthError, Site, derive_token

from .const import CONF_SESSION, CONF_SITE_ID, CONF_TOKEN, CONF_USER_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_HOST): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
        probatio.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        probatio.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)
REAUTH_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        ),
    }
)


def normalize_host(host: str) -> str:
    """Return the controller base URL with a scheme and without a trailing slash."""
    host = host.strip().rstrip("/")
    return host if "://" in host else f"http://{host}"


class SabatarkConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a controller site: credentials, then one site per entry."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._sites: list[Site] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow, or a placeholder until one is provided."""
        try:
            from .options_flow import SabatarkOptionsFlow
        except ModuleNotFoundError as err:
            if err.name != f"{__package__}.options_flow":
                raise
            return PlaceholderOptionsFlow()
        return SabatarkOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the controller URL and the account credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = normalize_host(user_input[CONF_HOST])
            email = user_input[CONF_EMAIL].strip()
            token = derive_token(user_input[CONF_PASSWORD], email)
            result = await self._async_login(host, email, token, errors, sites=True)
            if result is not None:
                user_id, session = result
                self._data = {
                    CONF_HOST: host,
                    CONF_EMAIL: email,
                    CONF_TOKEN: token,
                    CONF_USER_ID: user_id,
                    CONF_SESSION: session,
                }
                if not self._sites:
                    return self.async_abort(reason="no_sites")
                return await self.async_step_site()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_site(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask which site this entry covers."""
        if user_input is not None:
            site_id = int(user_input[CONF_SITE_ID])
            site = next(site for site in self._sites if site.id == site_id)
            await self.async_set_unique_id(f"{self._data[CONF_USER_ID]}_{site_id}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=site.name or f"Site {site_id}",
                data={**self._data, CONF_SITE_ID: site_id},
            )
        options = [
            SelectOptionDict(value=str(site.id), label=site.name or f"Site {site.id}")
            for site in self._sites
        ]
        return self.async_show_form(
            step_id="site",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_SITE_ID): SelectSelector(
                        SelectSelectorConfig(options=options)
                    )
                }
            ),
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication after the controller rejected the stored credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again and derive a new token."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            email = entry.data[CONF_EMAIL]
            token = derive_token(user_input[CONF_PASSWORD], email)
            result = await self._async_login(entry.data[CONF_HOST], email, token, errors)
            if result is not None:
                user_id, session = result
                if user_id != entry.data[CONF_USER_ID]:
                    return self.async_abort(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: token, CONF_SESSION: session}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
            description_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
        )

    async def _async_login(
        self, host: str, email: str, token: str, errors: dict[str, str], *, sites: bool = False
    ) -> tuple[int, dict[str, Any] | None] | None:
        client = AgatarkClient(host, email=email, token=token)
        try:
            hello = await client.login()
            if sites:
                self._sites = await client.sites()
        except AuthError:
            errors["base"] = "invalid_auth"
            return None
        except AgatarkError, aiohttp.ClientError, TimeoutError, ValueError:
            errors["base"] = "cannot_connect"
            return None
        except Exception:
            _LOGGER.exception("Unexpected error while logging in")
            errors["base"] = "unknown"
            return None
        finally:
            await client.close()
        if hello.user_id is None:
            errors["base"] = "invalid_auth"
            return None
        state = client.session_state
        return hello.user_id, state.to_dict() if state is not None else None


class PlaceholderOptionsFlow(OptionsFlow):
    """Options flow used while the integration offers no options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Abort: there is nothing to configure."""
        return self.async_abort(reason="no_options")
