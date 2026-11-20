"""Pure condition label rules (R6.1-R6.4)."""

import importlib
from datetime import datetime, timedelta

import pytest

from lineup.config import DEFAULT_THRESHOLDS
from lineup.models import Label, Level

BEGINNER = DEFAULT_THRESHOLDS["beginner"]
INTERMEDIATE = DEFAULT_THRESHOLDS["intermediate"]
BEYOND_NOTE = "Forecast available closer to the date"


class _LazyRules:
    # Import on first attribute use, inside the test body, so a missing rule
    # reports as a test failure rather than a collection or fixture error.
    def __getattr__(self, name):
        return getattr(importlib.import_module("lineup.logic.conditions"), name)


@pytest.fixture
def rules():
    return _LazyRules()


def _at(hour, minute=0):
    return datetime(2026, 11, 21, hour, minute)


def _forecast(values, first=6, last=18):
    """One value per hour on 21 Nov from `first` to `last`, with overrides by hour."""
    return {_at(h): values.get(h, 0.5) for h in range(first, last + 1)}


def _evaluate(rules, now, *, start=None, minutes=90, level=Level.BEGINNER,
              waves=None, winds=None, fetched_at=None, note="Forecast from 08:00"):
    return rules.evaluate(
        start=start or _at(10),
        minutes=minutes,
        level=level,
        waves=_forecast({}) if waves is None else waves,
        winds=_forecast({}) if winds is None else winds,
        fetched_at=fetched_at or now - timedelta(hours=1),
        now=now,
        thresholds_by_level=DEFAULT_THRESHOLDS,
        note=note,
    )


@pytest.mark.parametrize(
    ("start", "minutes", "expected"),
    [
        (_at(10), 90, [_at(10), _at(11)]),
        (_at(10), 60, [_at(10)]),
        (_at(10, 30), 90, [_at(10), _at(11)]),
        (_at(10, 45), 60, [_at(10), _at(11)]),
    ],
)
def test_r6_1_hours_in_window_covers_every_touched_hour(rules, start, minutes, expected):
    assert rules.hours_in_window(start, minutes) == expected


def test_r6_2_highest_wave_across_window_is_used(rules, now):
    condition = _evaluate(rules, now, waves=_forecast({10: 1.2, 11: 1.6}))
    assert condition.wave_m == 1.6
    assert condition.label == Label.MARGINAL


def test_r6_2_highest_wind_across_window_is_used(rules, now):
    condition = _evaluate(rules, now, winds=_forecast({10: 12.0, 11: 30.0}))
    assert condition.wind_kmh == 30.0
    assert condition.label == Label.MARGINAL


@pytest.mark.parametrize(
    ("wave", "wind", "expected"),
    [
        (1.50, 25, Label.GO),
        (1.51, 25, Label.MARGINAL),
        (1.5, 25.1, Label.MARGINAL),
        (2.0, 35, Label.MARGINAL),
        (2.01, 10, Label.NO_GO),
        (1.0, 35.1, Label.NO_GO),
    ],
)
def test_r6_3_beginner_threshold_edges(rules, wave, wind, expected):
    assert rules.classify(wave, wind, BEGINNER) == expected


@pytest.mark.parametrize(
    ("wave", "wind", "expected"),
    [
        (2.5, 30, Label.GO),
        (3.0, 40, Label.MARGINAL),
        (3.01, 40, Label.NO_GO),
    ],
)
def test_r6_3_intermediate_threshold_edges(rules, wave, wind, expected):
    assert rules.classify(wave, wind, INTERMEDIATE) == expected


def test_r6_3_evaluate_uses_the_session_level_thresholds(rules, now):
    waves = _forecast({10: 2.5, 11: 2.5})
    assert _evaluate(rules, now, waves=waves, level=Level.BEGINNER).label == Label.NO_GO
    assert _evaluate(rules, now, waves=waves, level=Level.INTERMEDIATE).label == Label.GO


def test_r6_4_missing_hour_is_unknown(rules, now):
    waves = _forecast({})
    del waves[_at(11)]
    condition = _evaluate(rules, now, waves=waves, note="Forecast from 08:00")
    assert condition.label == Label.UNKNOWN
    assert condition.note == "Forecast from 08:00"


def test_r6_4_empty_value_is_unknown(rules, now):
    condition = _evaluate(rules, now, winds=_forecast({11: None}))
    assert condition.label == Label.UNKNOWN


def test_r6_4_no_forecast_is_unknown(rules, now):
    condition = rules.evaluate(
        start=_at(10), minutes=90, level=Level.BEGINNER, waves={}, winds={},
        fetched_at=None, now=now, thresholds_by_level=DEFAULT_THRESHOLDS, note="",
    )
    assert condition.label == Label.UNKNOWN
    assert condition.wave_m is None
    assert condition.wind_kmh is None


def test_r6_4_forecast_fetched_over_12_hours_ago_is_unknown(rules, now):
    fetched = now - timedelta(hours=12, minutes=1)
    assert _evaluate(rules, now, fetched_at=fetched).label == Label.UNKNOWN


def test_r6_4_forecast_fetched_under_12_hours_ago_is_labelled(rules, now):
    fetched = now - timedelta(hours=11, minutes=59)
    assert _evaluate(rules, now, fetched_at=fetched).label == Label.GO


def test_r6_4_session_beyond_forecast_range_is_unknown_with_closer_note(rules, now):
    condition = _evaluate(rules, now, start=datetime(2026, 11, 30, 10, 0))
    assert condition.label == Label.UNKNOWN
    assert condition.note == BEYOND_NOTE


def test_r6_2_condition_carries_values_used_and_note(rules, now):
    condition = _evaluate(
        rules, now,
        waves=_forecast({10: 0.8, 11: 1.1}),
        winds=_forecast({10: 18.0, 11: 9.0}),
        note="Forecast from 08:00 (live update failed)",
    )
    assert condition.label == Label.GO
    assert condition.wave_m == 1.1
    assert condition.wind_kmh == 18.0
    assert condition.note == "Forecast from 08:00 (live update failed)"
