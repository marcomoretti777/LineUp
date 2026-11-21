"""Forecast service: hourly refresh, saved fallback and per-session labels (R7, R6.4).

The fetcher is always a fake, so these tests never touch the network.
"""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import insert, select, update

from conftest import make_member, make_session
from lineup import openmeteo, schema
from lineup.models import Label
from lineup.openmeteo import DaySunset, ForecastData, ForecastError, HourValue
from lineup.services import forecast

FIXTURES = Path(__file__).parent / "fixtures"
FIRST_HOUR = datetime(2026, 11, 20, 0, 0)


class FakeFetch:
    """Stands in for openmeteo.fetch_all: returns data or raises, and counts calls."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def fixture_data():
    """The recorded Open-Meteo answers (21-27 Nov 2026) as parsed ForecastData."""
    marine = json.loads((FIXTURES / "marine_ok.json").read_text())
    weather = json.loads((FIXTURES / "weather_ok.json").read_text())
    winds, sunsets = openmeteo.parse_weather(weather)
    return ForecastData(openmeteo.parse_marine(marine), winds, sunsets)


def small_data(first, hours=48, wave=1.0, wind=10.0):
    """Hand-made ForecastData with constant values from `first` for `hours` hours."""
    stamps = [first + timedelta(hours=i) for i in range(hours)]
    days = sorted({stamp.date() for stamp in stamps})
    return ForecastData(
        waves=[HourValue(stamp, wave) for stamp in stamps],
        winds=[HourValue(stamp, wind) for stamp in stamps],
        sunsets=[DaySunset(day, datetime.combine(day, datetime.min.time()) + timedelta(hours=17))
                 for day in days],
    )


def save_forecast(engine, fetched_at, first=FIRST_HOUR, hours=72, wave=1.0, wind=10.0):
    """Write a saved forecast straight into the tables, as an earlier fetch would."""
    stamps = [first + timedelta(hours=i) for i in range(hours)]
    days = sorted({stamp.date() for stamp in stamps})
    with engine.begin() as conn:
        conn.execute(insert(schema.forecast_hours), [
            {"hour_utc": stamp, "wave_height_m": wave, "wind_speed_kmh": wind,
             "fetched_at": fetched_at}
            for stamp in stamps
        ])
        conn.execute(insert(schema.forecast_days), [
            {"day": day, "sunset_utc": datetime.combine(day, datetime.min.time())
             + timedelta(hours=17, minutes=20), "fetched_at": fetched_at}
            for day in days
        ])


def set_setting_row(engine, key, value, at):
    """Insert one app_settings row directly."""
    with engine.begin() as conn:
        conn.execute(insert(schema.app_settings).values(key=key, value=value, updated_at=at))


def settings(engine):
    """Return app_settings as a {key: value} dict."""
    with engine.connect() as conn:
        rows = conn.execute(select(schema.app_settings.c.key, schema.app_settings.c.value)).all()
    return {row.key: row.value for row in rows}


def sessions_view(engine, *session_ids):
    """Load SessionViews through the shared query."""
    from lineup import db

    with engine.connect() as conn:
        return [db.get_session(conn, session_id) for session_id in session_ids]


@pytest.mark.parametrize(("minutes_old", "calls"), [(59, 0), (60, 1)])
def test_r7_1_fetches_only_when_saved_forecast_is_60_minutes_old(engine, now, minutes_old, calls):
    save_forecast(engine, fetched_at=now - timedelta(minutes=minutes_old))
    fake = FakeFetch(result=small_data(FIRST_HOUR))

    forecast.get_forecast(engine, now=now, fetch=fake)

    assert fake.calls == calls


def test_r7_3_successful_fetch_saves_hours_and_days_with_fetch_time(engine, now):
    fake = FakeFetch(result=fixture_data())

    bundle = forecast.get_forecast(engine, now=now, fetch=fake)

    with engine.connect() as conn:
        hours = conn.execute(select(schema.forecast_hours)).all()
        days = conn.execute(select(schema.forecast_days)).all()
    assert fake.calls == 1
    assert len(hours) == 168
    assert len(days) == 7
    assert {row.fetched_at for row in hours} == {now}
    assert {row.fetched_at for row in days} == {now}
    assert bundle.failed is False
    assert bundle.fetched_at == now
    assert bundle.sunsets[date(2026, 11, 21)] == datetime(2026, 11, 21, 17, 20)


def test_r7_3_refetch_replaces_rows_for_same_hours(engine, now):
    save_forecast(engine, fetched_at=now - timedelta(hours=2), hours=48, wave=1.0)
    fake = FakeFetch(result=small_data(FIRST_HOUR, hours=48, wave=2.2))

    bundle = forecast.get_forecast(engine, now=now, fetch=fake)

    with engine.connect() as conn:
        hours = conn.execute(select(schema.forecast_hours)).all()
        days = conn.execute(select(schema.forecast_days)).all()
    assert len(hours) == 48
    assert {row.wave_height_m for row in hours} == {2.2}
    assert {row.fetched_at for row in hours} == {now}
    assert len(days) == 2
    assert bundle.waves[datetime(2026, 11, 20, 10, 0)] == 2.2


def test_r7_2_r7_4_failure_uses_saved_data_and_records_attempt(engine, now):
    saved_at = datetime(2026, 11, 20, 7, 12)
    save_forecast(engine, fetched_at=saved_at)
    fake = FakeFetch(error=ForecastError("Open-Meteo request failed: timeout"))
    instructor = make_member(engine, role="instructor")
    session_id = make_session(engine, instructor, datetime(2026, 11, 20, 14, 0))

    bundle = forecast.get_forecast(engine, now=now, fetch=fake)
    conditions = forecast.conditions_for_sessions(
        engine, sessions_view(engine, session_id), now=now + timedelta(minutes=1), fetch=fake
    )

    assert bundle.failed is True
    assert bundle.fetched_at == saved_at
    assert bundle.note == "Forecast from 07:12 (live update failed)"
    assert bundle.waves[datetime(2026, 11, 20, 14, 0)] == 1.0
    stored = settings(engine)
    assert stored["last_forecast_attempt_at"] == now.isoformat()
    assert "timeout" in stored["last_forecast_error"]
    assert conditions[session_id].label == Label.GO
    assert conditions[session_id].note == "Forecast from 07:12 (live update failed)"


def test_r7_2_client_timeout_falls_back_to_saved_data(engine, now):
    save_forecast(engine, fetched_at=datetime(2026, 11, 20, 7, 12))

    def timeout_get(url, timeout):
        raise httpx.TimeoutException("timed out")

    bundle = forecast.get_forecast(
        engine, now=now, fetch=lambda: openmeteo.fetch_all(get=timeout_get)
    )

    assert bundle.failed is True
    assert bundle.note == "Forecast from 07:12 (live update failed)"


def test_r7_5_waits_ten_minutes_after_failed_attempt(engine, now):
    save_forecast(engine, fetched_at=now - timedelta(hours=3))
    fake = FakeFetch(error=ForecastError("HTTP 503"))

    forecast.get_forecast(engine, now=now, fetch=fake)
    assert fake.calls == 1

    at_0909 = forecast.get_forecast(engine, now=now + timedelta(minutes=9), fetch=fake)
    assert fake.calls == 1
    assert at_0909.note == "Forecast from 06:00 (live update failed)"

    forecast.get_forecast(engine, now=now + timedelta(minutes=10), fetch=fake)
    assert fake.calls == 2


def test_r7_6_saved_only_mode_never_calls_fetcher(engine, now):
    assert forecast.get_mode(engine) == "live"
    save_forecast(engine, fetched_at=datetime(2026, 11, 20, 6, 0))
    set_setting_row(engine, "forecast_mode", "saved_only", now)
    fake = FakeFetch(result=small_data(FIRST_HOUR))

    bundle = forecast.get_forecast(engine, now=now, fetch=fake)

    assert forecast.get_mode(engine) == "saved_only"
    assert fake.calls == 0
    assert bundle.note == "Forecast from 06:00 (saved data, live updates paused)"


def test_r6_4_no_saved_data_and_failure_gives_unknown(engine, now):
    instructor = make_member(engine, role="instructor")
    first = make_session(engine, instructor, datetime(2026, 11, 21, 10, 0))
    second = make_session(engine, instructor, datetime(2026, 11, 22, 10, 0))
    fake = FakeFetch(error=ForecastError("HTTP 400"))

    conditions = forecast.conditions_for_sessions(
        engine, sessions_view(engine, first, second), now=now, fetch=fake
    )

    assert set(conditions) == {first, second}
    for condition in conditions.values():
        assert condition.label == Label.UNKNOWN
        assert condition.note == "Forecast unavailable"


def test_r6_conditions_for_sessions_uses_saved_thresholds(engine, now):
    save_forecast(engine, fetched_at=now - timedelta(minutes=10), wave=1.0, wind=10.0)
    with engine.begin() as conn:
        conn.execute(
            update(schema.condition_thresholds)
            .where(schema.condition_thresholds.c.level == "beginner")
            .values(go_wave_m=0.5, marginal_wave_m=1.2)
        )
    instructor = make_member(engine, role="instructor")
    beginner = make_session(engine, instructor, datetime(2026, 11, 20, 14, 0), level="beginner")
    intermediate = make_session(engine, instructor, datetime(2026, 11, 20, 16, 0),
                                level="intermediate")
    fake = FakeFetch(result=small_data(FIRST_HOUR))

    conditions = forecast.conditions_for_sessions(
        engine, sessions_view(engine, beginner, intermediate), now=now, fetch=fake
    )

    assert fake.calls == 0
    assert set(conditions) == {beginner, intermediate}
    assert conditions[beginner].label == Label.MARGINAL
    assert conditions[intermediate].label == Label.GO
    assert conditions[beginner].wave_m == 1.0
    assert conditions[beginner].wind_kmh == 10.0


@pytest.mark.parametrize(("age", "label"), [
    (timedelta(hours=11, minutes=59), Label.GO),
    (timedelta(hours=12, minutes=1), Label.UNKNOWN),
])
def test_r6_4_saved_forecast_older_than_12_hours_is_unknown(engine, now, age, label):
    save_forecast(engine, fetched_at=now - age, first=FIRST_HOUR - timedelta(hours=24), hours=96)
    instructor = make_member(engine, role="instructor")
    session_id = make_session(engine, instructor, datetime(2026, 11, 20, 14, 0))
    fake = FakeFetch(error=ForecastError("timeout"))

    conditions = forecast.conditions_for_sessions(
        engine, sessions_view(engine, session_id), now=now, fetch=fake
    )

    assert conditions[session_id].label == label


def test_r6_4_session_beyond_saved_range_says_closer_to_date(engine, now):
    save_forecast(engine, fetched_at=now - timedelta(minutes=5))
    instructor = make_member(engine, role="instructor")
    session_id = make_session(engine, instructor, now + timedelta(days=10))

    conditions = forecast.conditions_for_sessions(
        engine, sessions_view(engine, session_id), now=now, fetch=FakeFetch()
    )

    assert conditions[session_id].label == Label.UNKNOWN
    assert conditions[session_id].note == "Forecast available closer to the date"


def test_r7_fresh_data_note_shows_lisbon_update_time(engine):
    summer_now = datetime(2026, 7, 1, 8, 30)
    fake = FakeFetch(result=small_data(datetime(2026, 7, 1, 0, 0)))

    fetched = forecast.get_forecast(engine, now=summer_now, fetch=fake)
    reused = forecast.get_forecast(engine, now=summer_now + timedelta(minutes=30), fetch=fake)

    assert fetched.note == "Forecast updated 09:30"
    assert fetched.failed is False
    assert fake.calls == 1
    assert reused.note == "Forecast updated 09:30"


def test_r2_7_sunset_for_returns_saved_sunset_or_none(engine, now):
    save_forecast(engine, fetched_at=now)

    assert forecast.sunset_for(engine, date(2026, 11, 21)) == datetime(2026, 11, 21, 17, 20)
    assert forecast.sunset_for(engine, date(2026, 12, 25)) is None
