"""Config flow for WHOOP Sense (OAuth2 via application credentials)."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow, selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SCOPES, WhoopClient, WhoopError
from .const import (
    CONF_WAKE_ENTITY,
    CONF_WAKE_WEEKDAY,
    CONF_WAKE_WEEKEND,
    DEFAULT_WAKE_WEEKDAY,
    DEFAULT_WAKE_WEEKEND,
    DOMAIN,
)


class OAuth2FlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    """Sign in with WHOOP."""

    DOMAIN = DOMAIN

    @property
    def logger(self) -> logging.Logger:
        return logging.getLogger(__name__)

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        return {"scope": SCOPES}

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        token = data["token"]["access_token"]

        async def _token() -> str:
            return token

        try:
            profile = await WhoopClient(async_get_clientsession(self.hass), _token).profile()
        except WhoopError:
            self.logger.exception("Could not read WHOOP profile")
            return self.async_abort(reason="cannot_connect")
        if not profile.get("user_id"):
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(str(profile["user_id"]))
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        self._abort_if_unique_id_configured()
        name = profile.get("first_name") or "WHOOP"
        return self.async_create_entry(title=f"WHOOP {name}".strip(), data=data)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return WhoopOptionsFlow()


class WhoopOptionsFlow(OptionsFlow):
    """Wake-up times for the bedtime recommendation."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_WAKE_WEEKDAY, default=opts.get(CONF_WAKE_WEEKDAY, DEFAULT_WAKE_WEEKDAY)
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_WAKE_WEEKEND, default=opts.get(CONF_WAKE_WEEKEND, DEFAULT_WAKE_WEEKEND)
                ): selector.TimeSelector(),
                vol.Optional(
                    CONF_WAKE_ENTITY,
                    description={"suggested_value": opts.get(CONF_WAKE_ENTITY)},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["input_datetime", "sensor"])
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
