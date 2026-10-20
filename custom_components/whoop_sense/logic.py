"""Turns raw WHOOP records into sensor values. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

SCORED = "SCORED"
HOUR_MS = 3_600_000
KJ_PER_KCAL = 4.184

ZONE_GREEN = "green"
ZONE_YELLOW = "yellow"
ZONE_RED = "red"

# Own estimate for the coming night: half of last night's shortfall, capped, on top of
# the baseline (WHOOP itself never put more than ~2.1 h of debt on a single night).
CATCH_UP_SHARE = 0.5
MAX_CATCH_UP_MS = 2 * HOUR_MS
DEFAULT_EFFICIENCY = 0.9


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def recovery_zone(score: float | None) -> str | None:
    """WHOOP colours: green 67-100, yellow 34-66, red 0-33."""
    if score is None:
        return None
    if score >= 67:
        return ZONE_GREEN
    if score >= 34:
        return ZONE_YELLOW
    return ZONE_RED


def _scored(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record and record.get("score_state") == SCORED and record.get("score"):
        return record
    return None


def latest_scored(records: list[dict[str, Any]], **match: Any) -> dict[str, Any] | None:
    """Newest scored record (the API returns newest first) whose fields equal `match`."""
    for rec in records:
        if all(rec.get(k) == v for k, v in match.items()) and _scored(rec):
            return rec
    return None


MORNING_START_HOUR = 4
MORNING_END_HOUR = 12


def waiting_for_recovery(recoveries: list[dict[str, Any]], now: datetime) -> bool:
    """True in the morning window while today's recovery is not scored yet."""
    if not MORNING_START_HOUR <= now.hour < MORNING_END_HOUR:
        return False
    rec = latest_scored(recoveries)
    created = parse_ts(rec.get("created_at")) if rec else None
    return created is None or created.astimezone(now.tzinfo).date() != now.date()


def _hours(ms: float | None) -> float | None:
    return None if ms is None else round(ms / HOUR_MS, 2)


def _kcal(kj: float | None) -> float | None:
    return None if kj is None else round(kj / KJ_PER_KCAL)


def asleep_ms(stages: dict[str, Any]) -> int:
    return sum(
        stages.get(k) or 0
        for k in (
            "total_light_sleep_time_milli",
            "total_slow_wave_sleep_time_milli",
            "total_rem_sleep_time_milli",
        )
    )


def need_ms(needed: dict[str, Any]) -> int:
    """WHOOP's sleep need for that night (nap credit is negative)."""
    return sum(
        needed.get(k) or 0
        for k in (
            "baseline_milli",
            "need_from_sleep_debt_milli",
            "need_from_recent_strain_milli",
            "need_from_recent_nap_milli",
        )
    )


def tonight_need_ms(sleep: dict[str, Any] | None) -> int | None:
    """Estimate for the next night: baseline plus half of what was missed last night."""
    if not (sleep := _scored(sleep)):
        return None
    score = sleep["score"]
    needed = score.get("sleep_needed") or {}
    baseline = needed.get("baseline_milli")
    if not baseline:
        return None
    missed = need_ms(needed) - asleep_ms(score.get("stage_summary") or {})
    return baseline + max(0, min(int(missed * CATCH_UP_SHARE), MAX_CATCH_UP_MS))


def next_wake(
    now: datetime,
    weekday: time,
    weekend: time,
    override: datetime | None = None,
) -> datetime:
    """Next wake-up after `now` (local, tz-aware). A future override wins."""
    if override is not None and override > now:
        return override
    for days in range(0, 8):
        day = (now + timedelta(days=days)).date()
        at = weekend if day.weekday() >= 5 else weekday
        candidate = datetime.combine(day, at, tzinfo=now.tzinfo)
        if candidate > now:
            return candidate
    raise AssertionError("unreachable")


def bedtime(wake: datetime, need: int | None, efficiency_pct: float | None) -> datetime | None:
    """When to be in bed so that `need` ms of actual sleep fit before `wake`."""
    if need is None:
        return None
    eff = (efficiency_pct or DEFAULT_EFFICIENCY * 100) / 100
    eff = min(1.0, max(0.7, eff))
    return wake - timedelta(milliseconds=need / eff)


def summarize(
    raw: dict[str, Any], now: datetime, wake: datetime
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Return (values, attributes) keyed by sensor key."""
    values: dict[str, Any] = {}
    attrs: dict[str, dict[str, Any]] = {}

    recoveries = raw.get("recoveries") or []
    sleeps = raw.get("sleeps") or []
    cycles = raw.get("cycles") or []
    workouts = raw.get("workouts") or []
    body = raw.get("body") or {}

    # Recovery
    rec = latest_scored(recoveries)
    rs = rec["score"] if rec else {}
    values["recovery"] = rs.get("recovery_score")
    values["recovery_zone"] = recovery_zone(rs.get("recovery_score"))
    values["resting_heart_rate"] = rs.get("resting_heart_rate")
    values["hrv"] = None if rs.get("hrv_rmssd_milli") is None else round(rs["hrv_rmssd_milli"], 1)
    values["spo2"] = None if rs.get("spo2_percentage") is None else round(rs["spo2_percentage"], 1)
    values["skin_temperature"] = (
        None if rs.get("skin_temp_celsius") is None else round(rs["skin_temp_celsius"], 2)
    )
    attrs["recovery"] = {
        "calibrating": rs.get("user_calibrating"),
        "pending": bool(recoveries) and recoveries[0].get("score_state") != SCORED,
        "updated": rec.get("updated_at") if rec else None,
    }

    # Main sleep (naps excluded)
    slp = latest_scored(sleeps, nap=False)
    ss = slp["score"] if slp else {}
    stages = ss.get("stage_summary") or {}
    needed = ss.get("sleep_needed") or {}
    values["sleep_performance"] = ss.get("sleep_performance_percentage")
    values["sleep_consistency"] = ss.get("sleep_consistency_percentage")
    values["sleep_efficiency"] = (
        None
        if ss.get("sleep_efficiency_percentage") is None
        else round(ss["sleep_efficiency_percentage"], 1)
    )
    values["respiratory_rate"] = (
        None if ss.get("respiratory_rate") is None else round(ss["respiratory_rate"], 1)
    )
    values["sleep_duration"] = _hours(asleep_ms(stages)) if stages else None
    values["time_in_bed"] = _hours(stages.get("total_in_bed_time_milli"))
    values["deep_sleep"] = _hours(stages.get("total_slow_wave_sleep_time_milli"))
    values["rem_sleep"] = _hours(stages.get("total_rem_sleep_time_milli"))
    values["light_sleep"] = _hours(stages.get("total_light_sleep_time_milli"))
    values["awake_time"] = _hours(stages.get("total_awake_time_milli"))
    values["sleep_cycles"] = stages.get("sleep_cycle_count")
    values["disturbances"] = stages.get("disturbance_count")
    values["sleep_start"] = parse_ts(slp.get("start")) if slp else None
    values["sleep_end"] = parse_ts(slp.get("end")) if slp else None
    values["sleep_need_last"] = _hours(need_ms(needed)) if needed else None
    attrs["sleep_need_last"] = {
        "baseline_h": _hours(needed.get("baseline_milli")),
        "sleep_debt_h": _hours(needed.get("need_from_sleep_debt_milli")),
        "strain_h": _hours(needed.get("need_from_recent_strain_milli")),
        "nap_h": _hours(needed.get("need_from_recent_nap_milli")),
    }

    tonight = tonight_need_ms(slp)
    values["sleep_need_tonight"] = _hours(tonight)
    bed = bedtime(wake, tonight, ss.get("sleep_efficiency_percentage"))
    values["bedtime"] = bed
    attrs["bedtime"] = {
        "wake_time": wake.isoformat(),
        "minutes_left": None if bed is None else round((bed - now).total_seconds() / 60),
    }

    # Current physiological cycle (day strain)
    cyc = cycles[0] if cycles else None
    cs = (cyc.get("score") or {}) if cyc else {}
    values["strain"] = None if cs.get("strain") is None else round(cs["strain"], 1)
    values["calories"] = _kcal(cs.get("kilojoule"))
    values["average_heart_rate"] = cs.get("average_heart_rate")
    values["max_heart_rate_today"] = cs.get("max_heart_rate")
    cycle_start = parse_ts(cyc.get("start")) if cyc else None
    attrs["strain"] = {"cycle_start": cycle_start.isoformat() if cycle_start else None}

    # Workouts
    wo = latest_scored(workouts)
    ws = wo["score"] if wo else {}
    w_start = parse_ts(wo.get("start")) if wo else None
    w_end = parse_ts(wo.get("end")) if wo else None
    values["last_workout"] = wo.get("sport_name") if wo else None
    values["last_workout_strain"] = None if ws.get("strain") is None else round(ws["strain"], 1)
    values["last_workout_calories"] = _kcal(ws.get("kilojoule"))
    values["last_workout_duration"] = (
        round((w_end - w_start).total_seconds() / 60) if w_start and w_end else None
    )
    zones = ws.get("zone_durations") or {}
    attrs["last_workout"] = {
        "start": w_start.isoformat() if w_start else None,
        "average_heart_rate": ws.get("average_heart_rate"),
        "max_heart_rate": ws.get("max_heart_rate"),
        "distance_km": None
        if ws.get("distance_meter") is None
        else round(ws["distance_meter"] / 1000, 2),
        **{
            f"zone_{i}_min": round((zones.get(f"zone_{n}_milli") or 0) / 60000)
            for i, n in enumerate(("zero", "one", "two", "three", "four", "five"))
        },
    }
    values["workouts_today"] = (
        sum(1 for w in workouts if (s := parse_ts(w.get("start"))) and s >= cycle_start)
        if cycle_start
        else None
    )

    # Body
    values["weight"] = body.get("weight_kilogram")
    values["max_heart_rate"] = body.get("max_heart_rate")
    values["height"] = body.get("height_meter")

    return values, attrs
