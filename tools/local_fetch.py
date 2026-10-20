"""Fetch real WHOOP data with the local tokens and print the computed sensor values.

Refreshes (and rotates) the token like the integration does. Saves the raw payload
to data/raw-<date>.json for building tests.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "whoop_sense"))
sys.path.insert(0, str(ROOT / "tools"))
from api import TOKEN_URL, WhoopClient  # noqa: E402
from local_auth import TOKENS, creds, save_tokens  # noqa: E402
from logic import next_wake, summarize  # noqa: E402


async def main() -> None:
    token = json.loads(TOKENS.read_text())
    c = creds()

    async with aiohttp.ClientSession() as session:

        async def access_token() -> str:
            nonlocal token
            if token["expires_at"] - time.time() < 60:
                async with session.post(
                    TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": token["refresh_token"],
                        "client_id": c["CLIENT_ID"],
                        "client_secret": c["CLIENT_SECRET"],
                        "scope": "offline",
                    },
                ) as resp:
                    body = await resp.json(content_type=None)
                    if resp.status != 200:
                        raise SystemExit(f"Refresh-Fehler {resp.status}: {body}")
                token = {**token, **body}
                save_tokens(token)
                print("(Token erneuert)")
            return token["access_token"]

        client = WhoopClient(session, access_token)
        raw = await client.activity()
        raw["body"] = await client.body()
        profile = await client.profile()

    (ROOT / "data").mkdir(exist_ok=True)
    out = ROOT / "data" / f"raw-{datetime.now():%Y-%m-%d}.json"
    out.write_text(json.dumps(raw, indent=2))

    now = datetime.now().astimezone()
    wake = next_wake(now, dtime(6, 30), dtime(9, 0))
    values, attrs = summarize(raw, now, wake)
    print(f"Konto: {profile.get('first_name')} (user_id {profile.get('user_id')})")
    for k, v in values.items():
        print(f"  {k:24} {v}")
    print("Attribute:")
    for k, v in attrs.items():
        print(f"  {k:24} {v}")
    print(f"Rohdaten: {out}")


if __name__ == "__main__":
    asyncio.run(main())
