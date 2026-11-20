"""Pure rules that turn hourly waves and wind into a session's conditions label.

Forecast maps are keyed by naive UTC hour. A missing key means the hour was
not in the forecast; a None value means Open-Meteo returned the hour empty.
Both make the label Unknown, because a guess from partial data could read
as safer than the sea really is.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta

from lineup.config import FORECAST_STALE
from lineup.models import Condition, Label
from lineup.timeutil import floor_hour

BEYOND_RANGE_NOTE = "Forecast available closer to the date"

Thresholds = tuple[float, float, float, float]
Hourly = Mapping[datetime, float | None]


def hours_in_window(start: datetime, minutes: int) -> list[datetime]:
    """Return every forecast hour a session touches, from its start to its last minute.

    Rules: R6.1.
    """
    # The end instant itself is not surfed, so 10:00 for 60 minutes stays in 10:00.
    last_minute = start + timedelta(minutes=minutes) - timedelta(minutes=1)
    hour, last = floor_hour(start), floor_hour(last_minute)
    hours = []
    while hour <= last:
        hours.append(hour)
        hour += timedelta(hours=1)
    return hours


def classify(wave: float, wind: float, thresholds: Thresholds) -> Label:
    """Label a wave height and wind speed as Go, Marginal or No-go against level thresholds.

    Rules: R6.3.
    """
    go_wave, go_wind, marginal_wave, marginal_wind = thresholds
    if wave <= go_wave and wind <= go_wind:
        return Label.GO
    if wave <= marginal_wave and wind <= marginal_wind:
        return Label.MARGINAL
    return Label.NO_GO


def evaluate(
    *,
    start: datetime,
    minutes: int,
    level: str,
    waves: Hourly,
    winds: Hourly,
    fetched_at: datetime | None,
    now: datetime,
    thresholds_by_level: Mapping[str, Thresholds],
    note: str,
) -> Condition:
    """Build a session's Condition from the forecast hours it touches.

    Rules: R6.1, R6.2, R6.3, R6.4.
    """
    unknown = Condition(Label.UNKNOWN, None, None, note)
    if fetched_at is None or not waves or not winds:
        return unknown
    if now - fetched_at > FORECAST_STALE:
        return unknown

    hours = hours_in_window(start, minutes)
    # The forecast ends at a fixed horizon, so a later session will get data
    # simply by waiting; say that instead of the generic forecast note.
    last_available = min(max(waves), max(winds))
    if hours[-1] > last_available:
        return Condition(Label.UNKNOWN, None, None, BEYOND_RANGE_NOTE)

    wave_values = [waves.get(hour) for hour in hours]
    wind_values = [winds.get(hour) for hour in hours]
    if None in wave_values or None in wind_values:
        return unknown

    wave, wind = max(wave_values), max(wind_values)
    label = classify(wave, wind, thresholds_by_level[level])
    return Condition(label, wave, wind, note)
