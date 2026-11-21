"""Open-Meteo client: requests, parsing and checks (spec section 10, R7.2)."""

import importlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from lineup import config

FIXTURES = Path(__file__).parent / "fixtures"


class _LazyClient:
    # Import on first attribute use, inside the test body, so a missing client
    # reports as a test failure rather than a collection or fixture error.
    def __getattr__(self, name):
        return getattr(importlib.import_module("lineup.openmeteo"), name)


@pytest.fixture
def om():
    return _LazyClient()


def _load(name):
    return json.loads((FIXTURES / name).read_text())


class _FakeResponse:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


def _getter(status_code=200, text="{}"):
    """A fake httpx.get that records its calls and returns one fixed response."""
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse(status_code, text)

    get.calls = calls
    return get


def _query(url):
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


def _marine_with(values):
    data = _load("marine_nulls.json")
    data["hourly"]["wave_height"] = values
    return data


def _weather_with(winds):
    data = _load("weather_ok.json")
    data["hourly"]["time"] = data["hourly"]["time"][: len(winds)]
    data["hourly"]["wind_speed_10m"] = winds
    return data


# Requests


def test_s10_marine_url_has_location_seven_days_gmt_and_wave_height(om):
    url = om.marine_url()
    query = _query(url)
    assert url.startswith("https://marine-api.open-meteo.com/v1/marine?")
    assert query["latitude"] == str(config.LATITUDE)
    assert query["longitude"] == str(config.LONGITUDE)
    assert query["forecast_days"] == "7"
    assert query["timezone"] == "GMT"
    assert query["hourly"] == "wave_height"


def test_s10_weather_url_has_location_seven_days_gmt_wind_sunset_kmh(om):
    url = om.weather_url()
    query = _query(url)
    assert url.startswith("https://api.open-meteo.com/v1/forecast?")
    assert query["latitude"] == str(config.LATITUDE)
    assert query["longitude"] == str(config.LONGITUDE)
    assert query["forecast_days"] == "7"
    assert query["timezone"] == "GMT"
    assert query["hourly"] == "wind_speed_10m"
    assert query["daily"] == "sunset"
    assert query["wind_speed_unit"] == "kmh"


# Parsing recorded responses


def test_s10_parse_marine_returns_one_value_per_hour(om):
    data = _load("marine_ok.json")
    waves = om.parse_marine(data)
    assert len(waves) == len(data["hourly"]["time"])
    hours = [w.hour_utc for w in waves]
    assert all(b - a == timedelta(hours=1) for a, b in zip(hours, hours[1:]))


def test_s10_parse_marine_times_are_naive_utc_and_heights_floats(om):
    data = _load("marine_ok.json")
    waves = om.parse_marine(data)
    first = waves[0]
    assert first.hour_utc == datetime.fromisoformat(data["hourly"]["time"][0])
    assert all(isinstance(w.hour_utc, datetime) and w.hour_utc.tzinfo is None for w in waves)
    assert all(isinstance(w.value, float) for w in waves)
    assert first.value == float(data["hourly"]["wave_height"][0])


def test_s10_parse_weather_returns_hourly_wind_speeds(om):
    data = _load("weather_ok.json")
    winds, _ = om.parse_weather(data)
    assert len(winds) == len(data["hourly"]["time"])
    assert all(w.hour_utc.tzinfo is None for w in winds)
    assert all(isinstance(w.value, float) for w in winds)
    assert winds[0].hour_utc == datetime.fromisoformat(data["hourly"]["time"][0])
    assert winds[0].value == float(data["hourly"]["wind_speed_10m"][0])


def test_s10_parse_weather_returns_one_sunset_per_day_as_naive_utc(om):
    data = _load("weather_ok.json")
    _, sunsets = om.parse_weather(data)
    assert [s.day for s in sunsets] == [date.fromisoformat(d) for d in data["daily"]["time"]]
    for s in sunsets:
        assert isinstance(s.sunset_utc, datetime)
        assert s.sunset_utc.tzinfo is None
        assert s.sunset_utc.date() == s.day
    assert sunsets[0].sunset_utc == datetime.fromisoformat(data["daily"]["sunset"][0])


# Value checks


def test_s10_nulls_become_none(om):
    waves = om.parse_marine(_load("marine_nulls.json"))
    assert [w.value for w in waves] == [1.2, None, 0.8, None]
    assert waves[0].hour_utc == datetime(2026, 11, 20, 9, 0)


@pytest.mark.parametrize("bad", [-0.1, 30.1, "1.2", True])
def test_s10_wave_outside_0_to_30_m_becomes_none(om, bad):
    waves = om.parse_marine(_marine_with([0, 30, bad, 1.5]))
    assert [w.value for w in waves] == [0.0, 30.0, None, 1.5]


@pytest.mark.parametrize("bad", [-1, 300.1, "12", False])
def test_s10_wind_outside_0_to_300_kmh_becomes_none(om, bad):
    winds, _ = om.parse_weather(_weather_with([0, 300, bad, 12.5]))
    assert [w.value for w in winds] == [0.0, 300.0, None, 12.5]


def test_s10_unparseable_sunset_becomes_none(om):
    data = _load("weather_ok.json")
    data["daily"]["sunset"][1] = "not a time"
    data["daily"]["sunset"][2] = None
    _, sunsets = om.parse_weather(data)
    assert sunsets[0].sunset_utc is not None
    assert sunsets[1].sunset_utc is None
    assert sunsets[2].sunset_utc is None
    assert len(sunsets) == len(data["daily"]["time"])


# Shape checks


def test_s10_missing_array_raises_forecast_error(om):
    with pytest.raises(om.ForecastError):
        om.parse_marine(_load("marine_missing_array.json"))
    weather = _load("weather_ok.json")
    del weather["daily"]
    with pytest.raises(om.ForecastError):
        om.parse_weather(weather)


def test_s10_arrays_of_different_lengths_raise_forecast_error(om):
    marine = _load("marine_ok.json")
    marine["hourly"]["wave_height"].pop()
    with pytest.raises(om.ForecastError):
        om.parse_marine(marine)

    hourly = _load("weather_ok.json")
    hourly["hourly"]["wind_speed_10m"].pop()
    with pytest.raises(om.ForecastError):
        om.parse_weather(hourly)

    daily = _load("weather_ok.json")
    daily["daily"]["sunset"].pop()
    with pytest.raises(om.ForecastError):
        om.parse_weather(daily)


# Fetching


def test_r7_2_timeout_raises_forecast_error(om):
    def get(url, **kwargs):
        raise httpx.TimeoutException("timed out")

    with pytest.raises(om.ForecastError):
        om.fetch_json(om.marine_url(), get=get)


def test_s10_http_400_raises_forecast_error_with_reason(om):
    body = (FIXTURES / "error_400.json").read_text()
    reason = json.loads(body)["reason"]
    with pytest.raises(om.ForecastError) as raised:
        om.fetch_json(om.marine_url(), get=_getter(400, body))
    assert reason in str(raised.value)


def test_s10_invalid_json_raises_forecast_error(om):
    with pytest.raises(om.ForecastError):
        om.fetch_json(om.marine_url(), get=_getter(200, "not json {"))


def test_r7_2_fetch_json_passes_config_timeout_to_getter(om):
    get = _getter(200, (FIXTURES / "marine_ok.json").read_text())
    data = om.fetch_json(om.marine_url(), get=get)
    assert data == _load("marine_ok.json")
    assert get.calls == [(om.marine_url(), {"timeout": config.HTTP_TIMEOUT_S})]


def test_s10_fetch_all_returns_waves_winds_and_sunsets(om):
    bodies = {
        "marine-api.open-meteo.com": (FIXTURES / "marine_ok.json").read_text(),
        "api.open-meteo.com": (FIXTURES / "weather_ok.json").read_text(),
    }

    def get(url, **kwargs):
        return _FakeResponse(200, bodies[urlsplit(url).hostname])

    result = om.fetch_all(get=get)
    assert result.waves == om.parse_marine(_load("marine_ok.json"))
    winds, sunsets = om.parse_weather(_load("weather_ok.json"))
    assert result.winds == winds
    assert result.sunsets == sunsets
