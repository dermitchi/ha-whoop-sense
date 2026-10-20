"""Polling coordinator for WHOOP Sense."""

from __future__ import annotations

from datetime import datetime, time, timedelta
import logging
from typing import Any

from aiohttp import ClientError, ClientResponseError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import WhoopAuthError, WhoopClient, WhoopError, WhoopRateLimited
from .const import (
    BODY_INTERVAL,
    CONF_WAKE_ENTITY,
    CONF_WAKE_WEEKDAY,
    CONF_WAKE_WEEKEND,
    DEFAULT_WAKE_WEEKDAY,
    DEFAULT_WAKE_WEEKEND,
    DOMAIN,
    FAST_INTERVAL,
    UPDATE_INTERVAL,
)
from .logic import next_wake, summarize, waiting_for_recovery

_LOGGER = logging.getLogger(__name__)

type WhoopConfigEntry = ConfigEntry[WhoopCoordinator]


def _time(value: str | None, fallback: str) -> time:
    try:
        return time.fromisoformat(value or fallback)
    except ValueError:
        return time.fromisoformat(fallback)


class WhoopData:
    """Raw API payloads plus the computed sensor values."""

    def __init__(self, raw: dict[str, Any], values: dict[str, Any], attrs: dict[str, Any]) -> None:
        self.raw = raw
        self.values = values
        self.attrs = attrs


class WhoopCoordinator(DataUpdateCoordinator[WhoopData]):
    """Fetches WHOOP every 15 minutes; body data every 6 hours."""

    config_entry: WhoopConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: WhoopConfigEntry,
        session: config_entry_oauth2_flow.OAuth2Session,
    ) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=UPDATE_INTERVAL
        )
        self._session = session
        self.client = WhoopClient(async_get_clientsession(hass), self._access_token)
        self.profile: dict[str, Any] = {}
        self._body: dict[str, Any] = {}
        self._body_at: datetime | None = None

    async def _access_token(self) -> str:
        try:
            await self._session.async_ensure_token_valid()
        except ClientResponseError as err:
            if 400 <= err.status < 500:
                raise WhoopAuthError(f"token refresh: HTTP {err.status}") from err
            raise WhoopError(f"token refresh: HTTP {err.status}") from err
        except ClientError as err:
            raise WhoopError(f"token refresh: {err}") from err
        return self._session.token["access_token"]

    def _override_wake(self) -> datetime | None:
        entity_id = self.config_entry.options.get(CONF_WAKE_ENTITY)
        if not entity_id or not (state := self.hass.states.get(entity_id)):
            return None
        if entity_id.startswith("input_datetime.") and not state.attributes.get("has_date"):
            t = dt_util.parse_time(state.state)
            if t is None:
                return None
            now = dt_util.now()
            at = datetime.combine(now.date(), t, tzinfo=now.tzinfo)
            return at if at > now else at + timedelta(days=1)
        parsed = dt_util.parse_datetime(state.state)
        if parsed is None:
            return None
        if parsed.tzinfo is None:  # input_datetime with date: local wall time
            parsed = parsed.replace(tzinfo=dt_util.get_default_time_zone())
        return dt_util.as_local(parsed)

    def compute(self, raw: dict[str, Any]) -> WhoopData:
        opts = self.config_entry.options
        now = dt_util.now()
        wake = next_wake(
            now,
            _time(opts.get(CONF_WAKE_WEEKDAY), DEFAULT_WAKE_WEEKDAY),
            _time(opts.get(CONF_WAKE_WEEKEND), DEFAULT_WAKE_WEEKEND),
            self._override_wake(),
        )
        values, attrs = summarize(raw, now, wake)
        return WhoopData(raw, values, attrs)

    @callback
    def recompute(self) -> None:
        """Refresh time-dependent values (bedtime, wake-up) without an API call."""
        if self.data is not None:
            self.async_set_updated_data(self.compute(self.data.raw))

    async def _async_update_data(self) -> WhoopData:
        try:
            if not self.profile:
                self.profile = await self.client.profile()
            now = dt_util.utcnow()
            if self._body_at is None or now - self._body_at >= BODY_INTERVAL:
                self._body = await self.client.body()
                self._body_at = now
            raw = await self.client.activity()
        except WhoopAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WhoopRateLimited as err:
            raise UpdateFailed(f"WHOOP rate limit, retry in {err.retry_after}s") from err
        except WhoopError as err:
            raise UpdateFailed(str(err)) from err
        raw["body"] = self._body
        fast = waiting_for_recovery(raw["recoveries"], dt_util.now())
        self.update_interval = FAST_INTERVAL if fast else UPDATE_INTERVAL
        return self.compute(raw)
