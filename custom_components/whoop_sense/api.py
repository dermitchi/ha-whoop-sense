"""Small async client for the WHOOP developer API (v2). No Home Assistant imports."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

API_BASE = "https://api.prod.whoop.com/developer"
AUTHORIZE_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
SCOPES = (
    "offline read:recovery read:cycles read:sleep read:workout "
    "read:profile read:body_measurement"
)
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class WhoopError(Exception):
    """Generic API failure (network, 5xx, bad payload)."""


class WhoopAuthError(WhoopError):
    """Token rejected; the user has to sign in again."""


class WhoopRateLimited(WhoopError):
    """HTTP 429; retry_after is seconds to wait (may be None)."""

    def __init__(self, retry_after: float | None) -> None:
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


class WhoopClient:
    """Read-only access to the endpoints the integration needs."""

    def __init__(
        self, session: aiohttp.ClientSession, access_token: Callable[[], Awaitable[str]]
    ) -> None:
        self._session = session
        self._access_token = access_token

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        token = await self._access_token()
        try:
            async with self._session.get(
                f"{API_BASE}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    raise WhoopAuthError(f"{path}: HTTP {resp.status}")
                if resp.status == 429:
                    raw = resp.headers.get("Retry-After") or resp.headers.get("X-RateLimit-Reset")
                    try:
                        retry = float(raw) if raw else None
                    except ValueError:
                        retry = None
                    raise WhoopRateLimited(retry)
                if resp.status == 404:
                    return None
                if resp.status >= 400:
                    raise WhoopError(f"{path}: HTTP {resp.status}")
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise WhoopError(f"{path}: {err}") from err

    async def _records(self, path: str, limit: int) -> list[dict[str, Any]]:
        data = await self._get(path, {"limit": limit})
        return list((data or {}).get("records") or [])

    async def profile(self) -> dict[str, Any]:
        return await self._get("/v2/user/profile/basic") or {}

    async def body(self) -> dict[str, Any]:
        return await self._get("/v2/user/measurement/body") or {}

    async def cycles(self, limit: int = 2) -> list[dict[str, Any]]:
        return await self._records("/v2/cycle", limit)

    async def recoveries(self, limit: int = 3) -> list[dict[str, Any]]:
        return await self._records("/v2/recovery", limit)

    async def sleeps(self, limit: int = 10) -> list[dict[str, Any]]:
        return await self._records("/v2/activity/sleep", limit)

    async def workouts(self, limit: int = 10) -> list[dict[str, Any]]:
        return await self._records("/v2/activity/workout", limit)

    async def activity(self) -> dict[str, list[dict[str, Any]]]:
        """Everything that changes during the day (4 requests)."""
        return {
            "cycles": await self.cycles(),
            "recoveries": await self.recoveries(),
            "sleeps": await self.sleeps(),
            "workouts": await self.workouts(),
        }
