from datetime import datetime, time, timedelta, timezone

from logic import (
    HOUR_MS,
    bedtime,
    latest_scored,
    next_wake,
    recovery_zone,
    summarize,
    tonight_need_ms,
)

TZ = timezone(timedelta(hours=2))


def _sleep(nap=False, state="SCORED", asleep_h=6.0, need_h=8.0, baseline_h=7.5, eff=90.0):
    third = int(asleep_h * HOUR_MS / 3)
    return {
        "id": "s1",
        "nap": nap,
        "start": "2026-10-19T21:30:00.000Z",
        "end": "2026-10-20T04:45:00.000Z",
        "score_state": state,
        "score": {
            "stage_summary": {
                "total_in_bed_time_milli": int(asleep_h / 0.9 * HOUR_MS),
                "total_awake_time_milli": 1_800_000,
                "total_light_sleep_time_milli": third,
                "total_slow_wave_sleep_time_milli": third,
                "total_rem_sleep_time_milli": third,
                "sleep_cycle_count": 4,
                "disturbance_count": 9,
            },
            "sleep_needed": {
                "baseline_milli": int(baseline_h * HOUR_MS),
                "need_from_sleep_debt_milli": int((need_h - baseline_h) * HOUR_MS),
                "need_from_recent_strain_milli": 0,
                "need_from_recent_nap_milli": 0,
            },
            "respiratory_rate": 15.234,
            "sleep_performance_percentage": 75,
            "sleep_consistency_percentage": 80,
            "sleep_efficiency_percentage": eff,
        },
    }


def test_recovery_zone_bounds():
    assert recovery_zone(None) is None
    assert recovery_zone(0) == "red"
    assert recovery_zone(33) == "red"
    assert recovery_zone(34) == "yellow"
    assert recovery_zone(66) == "yellow"
    assert recovery_zone(67) == "green"
    assert recovery_zone(100) == "green"


def test_latest_scored_skips_pending_and_naps():
    recs = [_sleep(state="PENDING_SCORE"), _sleep(nap=True), _sleep(asleep_h=5)]
    picked = latest_scored(recs, nap=False)
    assert picked is recs[2]


def test_tonight_need_adds_capped_catch_up():
    # needed 8 h, slept 6 h -> missed 2 h, half of it on top of baseline 7.5 -> 8.5 h
    assert tonight_need_ms(_sleep(asleep_h=6, need_h=8)) == int(8.5 * HOUR_MS)
    # slept more than needed -> just baseline
    assert tonight_need_ms(_sleep(asleep_h=9, need_h=8)) == int(7.5 * HOUR_MS)
    # huge deficit is capped at +2 h
    assert tonight_need_ms(_sleep(asleep_h=3, need_h=9)) == int(9.5 * HOUR_MS)
    assert tonight_need_ms(_sleep(asleep_h=4, need_h=9)) == int(9.5 * HOUR_MS)
    assert tonight_need_ms(_sleep(state="PENDING_SCORE")) is None


def test_next_wake_weekday_weekend_and_override():
    wd, we = time(6, 30), time(9, 0)
    fri_evening = datetime(2026, 10, 23, 21, 0, tzinfo=TZ)  # Friday
    assert next_wake(fri_evening, wd, we) == datetime(2026, 10, 24, 9, 0, tzinfo=TZ)
    sun_evening = datetime(2026, 10, 25, 21, 0, tzinfo=TZ)
    assert next_wake(sun_evening, wd, we) == datetime(2026, 10, 26, 6, 30, tzinfo=TZ)
    early = datetime(2026, 10, 20, 5, 0, tzinfo=TZ)  # Tuesday before wake-up
    assert next_wake(early, wd, we) == datetime(2026, 10, 20, 6, 30, tzinfo=TZ)
    override = datetime(2026, 10, 21, 7, 45, tzinfo=TZ)
    assert next_wake(early, wd, we, override) == override
    assert next_wake(early, wd, we, early - timedelta(hours=1)).hour == 6  # past override ignored


def test_bedtime_uses_efficiency():
    wake = datetime(2026, 10, 21, 6, 30, tzinfo=TZ)
    # 8 h need at 80 % efficiency -> 10 h in bed
    assert bedtime(wake, 8 * HOUR_MS, 80) == wake - timedelta(hours=10)
    # missing efficiency -> 90 %; absurd values clamped to >= 70 %
    assert bedtime(wake, 9 * HOUR_MS, None) == wake - timedelta(hours=10)
    assert bedtime(wake, 7 * HOUR_MS, 10) == wake - timedelta(hours=10)
    assert bedtime(wake, None, 90) is None


def test_summarize_full_payload():
    now = datetime(2026, 10, 20, 18, 0, tzinfo=TZ)
    wake = datetime(2026, 10, 21, 6, 30, tzinfo=TZ)
    raw = {
        "recoveries": [
            {
                "score_state": "SCORED",
                "updated_at": "2026-10-20T05:00:00Z",
                "score": {
                    "user_calibrating": False,
                    "recovery_score": 44,
                    "resting_heart_rate": 58,
                    "hrv_rmssd_milli": 61.234,
                    "spo2_percentage": 96.71,
                    "skin_temp_celsius": 33.456,
                },
            }
        ],
        "sleeps": [_sleep()],
        "cycles": [
            {
                "start": "2026-10-20T04:45:00Z",
                "end": None,
                "score_state": "SCORED",
                "score": {"strain": 9.87, "kilojoule": 8368, "average_heart_rate": 70, "max_heart_rate": 160},
            }
        ],
        "workouts": [
            {
                "start": "2026-10-20T15:00:00Z",
                "end": "2026-10-20T16:05:00Z",
                "sport_name": "running",
                "score_state": "SCORED",
                "score": {
                    "strain": 11.26,
                    "kilojoule": 2092,
                    "average_heart_rate": 150,
                    "max_heart_rate": 180,
                    "distance_meter": 10234,
                    "zone_durations": {"zone_three_milli": 1_200_000},
                },
            },
            {"start": "2026-10-19T15:00:00Z", "score_state": "SCORED", "score": {"strain": 5}},
        ],
        "body": {"weight_kilogram": 72.5, "max_heart_rate": 198, "height_meter": 1.8},
    }
    v, a = summarize(raw, now, wake)
    assert v["recovery"] == 44 and v["recovery_zone"] == "yellow"
    assert v["hrv"] == 61.2 and v["spo2"] == 96.7 and v["skin_temperature"] == 33.46
    assert v["sleep_duration"] == 6.0
    assert v["sleep_need_last"] == 8.0
    assert v["sleep_need_tonight"] == 8.5
    assert v["bedtime"] == wake - timedelta(hours=8.5 / 0.9)
    assert a["bedtime"]["minutes_left"] == round((v["bedtime"] - now).total_seconds() / 60)
    assert v["sleep_start"].tzinfo is not None
    assert v["strain"] == 9.9 and v["calories"] == 2000
    assert v["last_workout"] == "running"
    assert v["last_workout_duration"] == 65
    assert v["last_workout_calories"] == 500
    assert a["last_workout"]["zone_3_min"] == 20
    assert a["last_workout"]["distance_km"] == 10.23
    assert v["workouts_today"] == 1
    assert v["weight"] == 72.5


def test_summarize_empty_account():
    now = datetime(2026, 10, 20, 18, 0, tzinfo=TZ)
    v, _ = summarize({}, now, now + timedelta(hours=12))
    assert all(val is None for val in v.values())
