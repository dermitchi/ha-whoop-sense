"""Application credentials (OAuth2) for WHOOP Sense."""

from __future__ import annotations

from typing import Any

from homeassistant.components.application_credentials import (
    AuthImplementation,
    AuthorizationServer,
    ClientCredential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from .api import AUTHORIZE_URL, TOKEN_URL

_SERVER = AuthorizationServer(authorize_url=AUTHORIZE_URL, token_url=TOKEN_URL)


class WhoopAuthImplementation(AuthImplementation):
    """WHOOP wants the scope on refresh and rotates the refresh token."""

    async def _async_refresh_token(self, token: dict[str, Any]) -> dict[str, Any]:
        new_token = await self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": token["refresh_token"],
                "scope": "offline",
            }
        )
        return {**token, **new_token}


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    return _SERVER


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> config_entry_oauth2_flow.AbstractOAuth2Implementation:
    return WhoopAuthImplementation(hass, auth_domain, credential, _SERVER)


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    return {
        "dashboard_url": "https://developer-dashboard.whoop.com",
        "redirect_url": "https://my.home-assistant.io/redirect/oauth",
    }
