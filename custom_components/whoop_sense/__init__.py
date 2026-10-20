"""WHOOP Sense: recovery, sleep and strain from WHOOP in Home Assistant."""

from __future__ import annotations

from datetime import datetime

from aiohttp import ClientError, ClientResponseError

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.event import async_track_time_interval

from .const import RECOMPUTE_INTERVAL
from .coordinator import WhoopConfigEntry, WhoopCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: WhoopConfigEntry) -> bool:
    implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
        hass, entry
    )
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    try:
        await session.async_ensure_token_valid()
    except ClientResponseError as err:
        if 400 <= err.status < 500:
            raise ConfigEntryAuthFailed from err
        raise ConfigEntryNotReady from err
    except ClientError as err:
        raise ConfigEntryNotReady from err

    coordinator = WhoopCoordinator(hass, entry, session)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    @callback
    def _tick(_now: datetime) -> None:
        coordinator.recompute()

    entry.async_on_unload(async_track_time_interval(hass, _tick, RECOMPUTE_INTERVAL))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: WhoopConfigEntry) -> None:
    """New wake-up times only change computed values: recompute, no API call."""
    entry.runtime_data.recompute()


async def async_unload_entry(hass: HomeAssistant, entry: WhoopConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
