"""Open-Meteo client: build the two requests, fetch them, and parse the answers.

Both requests ask for timezone=GMT, so every timestamp is already UTC and is
returned naive to match the database. This file holds no database code and
never reads the clock; the forecast service decides when to call it.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from lineup import config

MARINE_BASE = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_BASE = "https://api.open-meteo.com/v1/forecast"
MAX_WAVE_M = 30.0
MAX_WIND_KMH = 300.0


@dataclass(frozen=True)
class HourValue:
    """One hourly reading; value is None when Open-Meteo gave nothing usable."""

    hour_utc: datetime
    value: float | None


@dataclass(frozen=True)
class DaySunset:
    """The sunset for one forecast day; sunset_utc is None when unparseable."""

    day: date
    sunset_utc: datetime | None


@dataclass(frozen=True)
class ForecastData:
    """Everything one successful fetch of both feeds gives."""

    waves: list[HourValue]
    winds: list[HourValue]
    sunsets: list[DaySunset]


class ForecastError(Exception):
    """A feed failed: timeout, HTTP error, bad JSON or an unexpected shape."""


def _common_params() -> dict[str, Any]:
    return {
        "latitude": config.LATITUDE,
        "longitude": config.LONGITUDE,
        "forecast_days": 7,
        "timezone": "GMT",
    }


def marine_url() -> str:
    """Return the marine request URL for hourly wave height at the club's beach.

    Rules: spec section 10.
    """
    return f"{MARINE_BASE}?{urlencode({**_common_params(), 'hourly': 'wave_height'})}"


def weather_url() -> str:
    """Return the weather request URL for hourly wind in km/h and daily sunset.

    Rules: spec section 10.
    """
    params = {
        **_common_params(),
        "hourly": "wind_speed_10m",
        "daily": "sunset",
        "wind_speed_unit": "kmh",
    }
    return f"{WEATHER_BASE}?{urlencode(params)}"


def fetch_json(url: str, get: Callable[..., Any] = httpx.get) -> dict:
    """Fetch one feed and return its JSON object, raising ForecastError on any failure.

    Rules: R7.2, spec section 10.
    """
    try:
        response = get(url, timeout=config.HTTP_TIMEOUT_S)
    except httpx.HTTPError as error:
        raise ForecastError(f"Open-Meteo request failed: {error!r}") from error
    if response.status_code != 200:
        raise ForecastError(
            f"Open-Meteo returned HTTP {response.status_code}: {_reason(response)}"
        )
    try:
        data = response.json()
    except ValueError as error:
        raise ForecastError("Open-Meteo returned invalid JSON") from error
    if not isinstance(data, dict):
        raise ForecastError("Open-Meteo returned JSON that is not an object")
    return data


def _reason(response: Any) -> str:
    # A 400 body explains itself in "reason"; other errors may carry no JSON at all.
    try:
        body = response.json()
    except ValueError:
        return "no reason given"
    if isinstance(body, dict) and body.get("reason"):
        return str(body["reason"])
    return "no reason given"


def parse_marine(data: dict) -> list[HourValue]:
    """Turn a marine response into one wave height per hour, in metres.

    Rules: spec section 10.
    """
    hourly = _block(data, "hourly")
    return _hours(_array(hourly, "time"), _array(hourly, "wave_height"), MAX_WAVE_M)


def parse_weather(data: dict) -> tuple[list[HourValue], list[DaySunset]]:
    """Turn a weather response into hourly wind speeds (km/h) and one sunset per day.

    Rules: spec section 10.
    """
    hourly = _block(data, "hourly")
    winds = _hours(_array(hourly, "time"), _array(hourly, "wind_speed_10m"), MAX_WIND_KMH)
    daily = _block(data, "daily")
    days, sunsets = _array(daily, "time"), _array(daily, "sunset")
    if len(days) != len(sunsets):
        raise ForecastError("daily.time and daily.sunset have different lengths")
    try:
        parsed_days = [date.fromisoformat(day) for day in days]
    except (TypeError, ValueError) as error:
        raise ForecastError("daily.time holds an unparseable date") from error
    return winds, [
        DaySunset(day, _sunset(text)) for day, text in zip(parsed_days, sunsets)
    ]


def fetch_all(get: Callable[..., Any] = httpx.get) -> ForecastData:
    """Fetch and parse both feeds, raising ForecastError if either one fails.

    Rules: R7.2, spec section 10.
    """
    waves = parse_marine(fetch_json(marine_url(), get=get))
    winds, sunsets = parse_weather(fetch_json(weather_url(), get=get))
    return ForecastData(waves=waves, winds=winds, sunsets=sunsets)


def _block(data: Any, key: str) -> dict:
    block = data.get(key) if isinstance(data, dict) else None
    if not isinstance(block, dict):
        raise ForecastError(f"response has no '{key}' block")
    return block


def _array(block: dict, key: str) -> list:
    values = block.get(key)
    if not isinstance(values, list):
        raise ForecastError(f"response has no '{key}' array")
    return values


def _hours(times: list, values: list, max_value: float) -> list[HourValue]:
    # Pairing arrays of unequal length would shift every value onto the wrong hour.
    if len(times) != len(values):
        raise ForecastError("hourly.time and its value array have different lengths")
    try:
        hours = [_naive_utc(datetime.fromisoformat(text)) for text in times]
    except (TypeError, ValueError) as error:
        raise ForecastError("hourly.time holds an unparseable time") from error
    return [HourValue(hour, _clean(value, max_value)) for hour, value in zip(hours, values)]


def _clean(value: Any, max_value: float) -> float | None:
    # bool is an int subclass, so exclude it explicitly; out-of-range readings are
    # sensor or model glitches and would mislabel a session.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or not 0 <= value <= max_value:
        return None
    return float(value)


def _sunset(text: Any) -> datetime | None:
    try:
        return _naive_utc(datetime.fromisoformat(text))
    except (TypeError, ValueError):
        return None


def _naive_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)
