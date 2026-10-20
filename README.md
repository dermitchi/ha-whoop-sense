# WHOOP Sense

WHOOP recovery, sleep, strain and workouts in Home Assistant – via the official WHOOP developer API (v2), plus a recommended bedtime based on your sleep need and wake-up time.

## Sensors

- **Recovery:** recovery %, recovery zone (green / yellow / red), resting heart rate, HRV, blood oxygen, skin temperature
- **Sleep (last main sleep, naps excluded):** performance, consistency, efficiency, respiratory rate, sleep duration, time in bed, deep / REM / light sleep, awake time, sleep cycles, disturbances, fell asleep, woke up, sleep need last night
- **Tonight:** sleep need tonight (estimate: baseline + half of last night's shortfall, max +2 h) and **recommended bedtime** (wake-up − need ÷ your sleep efficiency)
- **Day:** day strain, calories, average and max heart rate
- **Workouts:** last workout (sport, strain, calories, duration, heart-rate zones as attributes), workouts today
- **Body:** weight, max heart rate, height (disabled by default)

WHOOP is polled every 15 minutes (≈400 requests/day, limit is 10,000). Body data every 6 hours. WHOOP only publishes values once they are scored (after waking up or after a workout) – there is no live heart rate in the API.

## Setup

1. Create an app at <https://developer-dashboard.whoop.com>:
   - scopes: `read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement` (and `offline` if offered)
   - redirect URI: `https://my.home-assistant.io/redirect/oauth`
2. HACS → ⋮ → *Custom repositories* → `https://github.com/dermitchi/ha-whoop-sense`, category *Integration*. Install **WHOOP Sense**, restart Home Assistant.
3. *Settings → Devices & services → Add integration → WHOOP Sense*, enter Client ID and Client Secret, sign in with WHOOP.
4. Optional: *Configure* to set wake-up times (weekdays / weekend) or an entity (e.g. an `input_datetime` alarm) that overrides them.

## Development

```
python -m venv .venv && .venv/bin/pip install pytest-homeassistant-custom-component
.venv/bin/pytest
```

`tools/local_auth.py` and `tools/local_fetch.py` sign in and fetch real data outside Home Assistant (needs `.creds` with `CLIENT_ID=` / `CLIENT_SECRET=` and the redirect URI `http://localhost:8790/callback`).
