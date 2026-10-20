"""End-to-end tests inside a real Home Assistant core (pytest-homeassistant-custom-component)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "whoop_sense"
API = "https://api.prod.whoop.com/developer"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"

RAW = json.loads((Path(__file__).parent / "fixture.json").read_text())


def _mock_api(aioclient_mock, status: int = 200) -> None:
    aioclient_mock.get(f"{API}/v2/user/profile/basic", json={"user_id": 42, "first_name": "Test"}, status=status)
    aioclient_mock.get(f"{API}/v2/user/measurement/body", json=RAW["body"], status=status)
    aioclient_mock.get(f"{API}/v2/cycle", json={"records": RAW["cycles"]}, status=status)
    aioclient_mock.get(f"{API}/v2/recovery", json={"records": RAW["recoveries"]}, status=status)
    aioclient_mock.get(f"{API}/v2/activity/sleep", json={"records": RAW["sleeps"]}, status=status)
    aioclient_mock.get(f"{API}/v2/activity/workout", json={"records": RAW["workouts"]}, status=status)


async def _setup(hass: HomeAssistant, expires_in: float = 3600) -> MockConfigEntry:
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(hass, DOMAIN, ClientCredential("cid", "secret"), DOMAIN)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="42",
        title="WHOOP Test",
        data={
            "auth_implementation": DOMAIN,
            "token": {
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "expires_at": time.time() + expires_in,
                "expires_in": expires_in,
                "token_type": "bearer",
            },
        },
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_setup_creates_sensors(hass: HomeAssistant, aioclient_mock) -> None:
    _mock_api(aioclient_mock)
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED
    states = {s.entity_id: s for s in hass.states.async_all("sensor")}
    assert len(states) == 34  # height is disabled by default
    rec = next(s for s in states.values() if s.attributes.get("unit_of_measurement") == "%" and s.state == "44")
    assert rec.attributes["calibrating"] is False
    zone = [s for s in states.values() if s.attributes.get("options") == ["green", "yellow", "red"]]
    assert zone and zone[0].state == "yellow"
    assert all(s.state != "unavailable" for s in states.values())


async def test_expired_token_is_refreshed_with_scope(hass: HomeAssistant, aioclient_mock) -> None:
    _mock_api(aioclient_mock)
    aioclient_mock.post(
        TOKEN_URL,
        json={"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600, "token_type": "bearer"},
    )
    entry = await _setup(hass, expires_in=-10)
    assert entry.state is ConfigEntryState.LOADED
    refresh = [c for c in aioclient_mock.mock_calls if str(c[1]) == TOKEN_URL]
    assert refresh, "token endpoint not called"
    body = refresh[0][2]
    assert body["grant_type"] == "refresh_token" and body["scope"] == "offline"
    assert entry.data["token"]["refresh_token"] == "new-refresh"  # rotation stored


async def test_rejected_refresh_starts_reauth(hass: HomeAssistant, aioclient_mock) -> None:
    _mock_api(aioclient_mock)
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    entry = await _setup(hass, expires_in=-10)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_api_401_starts_reauth(hass: HomeAssistant, aioclient_mock) -> None:
    _mock_api(aioclient_mock, status=401)
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress())


async def test_server_error_retries(hass: HomeAssistant, aioclient_mock) -> None:
    _mock_api(aioclient_mock, status=500)
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_options_change_recomputes_without_api(hass: HomeAssistant, aioclient_mock) -> None:
    _mock_api(aioclient_mock)
    entry = await _setup(hass)
    calls = aioclient_mock.call_count
    bed = next(s for s in hass.states.async_all("sensor") if "wake_time" in s.attributes)
    hass.config_entries.async_update_entry(
        entry, options={"wake_weekday": "05:00:00", "wake_weekend": "05:00:00"}
    )
    await hass.async_block_till_done()
    new = hass.states.get(bed.entity_id)
    assert new.attributes["wake_time"] != bed.attributes["wake_time"]
    assert aioclient_mock.call_count == calls
