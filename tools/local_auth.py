"""One-time local WHOOP login for testing outside Home Assistant.

Opens the WHOOP login in the browser, catches the redirect on localhost:8790
and stores the tokens in .tokens.json (chmod 600, gitignored).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "whoop_sense"))
from api import AUTHORIZE_URL, SCOPES, TOKEN_URL  # noqa: E402

REDIRECT = "http://localhost:8790/callback"
TOKENS = ROOT / ".tokens.json"


def creds() -> dict[str, str]:
    out = {}
    for line in (ROOT / ".creds").read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def save_tokens(token: dict) -> None:
    token["expires_at"] = time.time() + float(token.get("expires_in", 3600))
    TOKENS.write_text(json.dumps(token, indent=2))
    os.chmod(TOKENS, 0o600)


async def main() -> None:
    c = creds()
    state = secrets.token_urlsafe(16)
    done: asyncio.Future = asyncio.get_running_loop().create_future()

    async def callback(request: web.Request) -> web.Response:
        if request.query.get("state") != state:
            return web.Response(text="state mismatch", status=400)
        if "error" in request.query:
            done.set_exception(RuntimeError(dict(request.query)))
            return web.Response(text=f"Fehler: {dict(request.query)}")
        done.set_result(request.query["code"])
        return web.Response(text="WHOOP verbunden. Du kannst dieses Fenster schliessen.")

    app = web.Application()
    app.router.add_get("/callback", callback)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "localhost", 8790).start()

    url = AUTHORIZE_URL + "?" + urlencode(
        {
            "response_type": "code",
            "client_id": c["CLIENT_ID"],
            "redirect_uri": REDIRECT,
            "scope": SCOPES,
            "state": state,
        }
    )
    subprocess.run(["open", url], check=False)
    print("Browser geöffnet, warte auf Login …", flush=True)
    code = await asyncio.wait_for(done, timeout=600)
    await runner.cleanup()

    async with aiohttp.ClientSession() as s, s.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": c["CLIENT_ID"],
            "client_secret": c["CLIENT_SECRET"],
        },
    ) as resp:
        body = await resp.json(content_type=None)
        if resp.status != 200:
            raise SystemExit(f"Token-Fehler {resp.status}: {body}")
    save_tokens(body)
    print("OK, Token gespeichert. Refresh-Token:", "ja" if body.get("refresh_token") else "NEIN",
          "| Scopes:", body.get("scope"))


if __name__ == "__main__":
    asyncio.run(main())
