"""Forecast actions: refresh from Open-Meteo at most hourly, fall back to saved data, label sessions.

Owner: Member 3 (Sessions and forecast lane). Spec section 10 sets the order
of checks. These are read-only lookups with no actor, so they return plain
data rather than Result; nothing here ever blocks booking (R6.5).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import Engine

from lineup import openmeteo
from lineup.config import FORECAST_REFRESH, FORECAST_RETRY, MAX_DAYS_AHEAD
from lineup.logic import conditions
from lineup.models import Condition, SessionView
from lineup.openmeteo import ForecastData, ForecastError
from lineup.queries import forecast as queries
from lineup.timeutil import fmt_time, utcnow

MODE_KEY = "forecast_mode"
ATTEMPT_KEY = "last_forecast_attempt_at"
ERROR_KEY = "last_forecast_error"
LIVE = "live"
SAVED_ONLY = "saved_only"

UNAVAILABLE_NOTE = "Forecast unavailable"

# Sessions that already started still need their early hours, and screens look
# up to MAX_DAYS_AHEAD; one extra day each side covers the edges.
_LOOK_BACK = timedelta(days=1)
_LOOK_AHEAD = timedelta(days=MAX_DAYS_AHEAD + 1)


@dataclass(frozen=True)
class ForecastBundle:
    """The forecast every label is built from, with the note shown under it."""

    waves: dict[datetime, float | None]
    winds: dict[datetime, float | None]
    sunsets: dict[date, datetime | None]
    fetched_at: datetime | None
    note: str
    failed: bool


def get_mode(engine: Engine) -> str:
    """Return the forecast mode: "saved_only" when an admin paused live updates, else "live".

    Rules: R7.6.
    """
    with engine.connect() as conn:
        return _mode(queries.get_setting(conn, MODE_KEY))


def _mode(value: str | None) -> str:
    # Anything other than an explicit pause keeps live updates on.
    return SAVED_ONLY if value == SAVED_ONLY else LIVE


def get_forecast(engine: Engine, now: datetime | None = None,
                 fetch: Callable[[], ForecastData] | None = None) -> ForecastBundle:
    """Return the forecast, calling Open-Meteo only when the saved one is due for a refresh.

    Rules: R7.1, R7.2, R7.3, R7.4, R7.5, R7.6.
    """
    now = now or utcnow()
    fetch = fetch or openmeteo.fetch_all

    with engine.connect() as conn:
        mode = _mode(queries.get_setting(conn, MODE_KEY))
        newest = queries.newest_fetch_time(conn)
        last_attempt = _parse_time(queries.get_setting(conn, ATTEMPT_KEY))
        last_error = queries.get_setting(conn, ERROR_KEY)

    # The connection above is closed on purpose: a transaction held open across
    # a 5-second network call would block every other writer meanwhile.
    fetched = failed = False
    if _should_fetch(mode, newest, last_attempt, last_error, now):
        try:
            data = fetch()
        except ForecastError as error:
            failed = True
            with engine.begin() as conn:
                queries.set_setting(conn, ATTEMPT_KEY, now.isoformat(), now)
                queries.set_setting(conn, ERROR_KEY, str(error) or type(error).__name__, now)
        else:
            fetched = True
            with engine.begin() as conn:
                queries.save_hours(conn, data.waves, data.winds, now)
                queries.save_days(conn, data.sunsets, now)
                queries.set_setting(conn, ATTEMPT_KEY, now.isoformat(), now)
                queries.set_setting(conn, ERROR_KEY, None, now)
    elif mode == LIVE and last_error and _is_due(newest, now):
        # Still inside the retry back-off after a failure: the saved data is a fallback.
        failed = True

    with engine.connect() as conn:
        fetched_at = queries.newest_fetch_time(conn)
        waves, winds = queries.load_hours(conn, now - _LOOK_BACK, now + _LOOK_AHEAD)
        sunsets = queries.load_sunsets(conn, (now - _LOOK_BACK).date(),
                                       (now + _LOOK_AHEAD).date())

    note = _note(mode, fetched_at, fetched, failed, now)
    return ForecastBundle(waves, winds, sunsets, fetched_at, note, failed)


def _is_due(newest: datetime | None, now: datetime) -> bool:
    return newest is None or now - newest >= FORECAST_REFRESH


def _should_fetch(mode: str, newest: datetime | None, last_attempt: datetime | None,
                  last_error: str | None, now: datetime) -> bool:
    if mode == SAVED_ONLY:
        return False
    if not _is_due(newest, now):
        return False
    if last_error and last_attempt is not None and now - last_attempt < FORECAST_RETRY:
        return False
    return True


def _note(mode: str, fetched_at: datetime | None, fetched: bool, failed: bool,
          now: datetime) -> str:
    if fetched_at is None:
        return UNAVAILABLE_NOTE
    clock = fmt_time(fetched_at)
    if fetched or (not failed and not _is_due(fetched_at, now)):
        return f"Forecast updated {clock}"
    if mode == SAVED_ONLY:
        return f"Forecast from {clock} (saved data, live updates paused)"
    return f"Forecast from {clock} (live update failed)"


def _parse_time(value: str | None) -> datetime | None:
    # A hand-edited or corrupt setting must not stop the forecast; treat it as unset.
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def conditions_for_sessions(engine: Engine, sessions: Iterable[SessionView],
                            now: datetime | None = None,
                            fetch: Callable[[], ForecastData] | None = None
                            ) -> dict[int, Condition]:
    """Return the conditions label for each session, keyed by session id.

    Rules: R6.1, R6.2, R6.3, R6.4, R6.5, R7.
    """
    now = now or utcnow()
    sessions = list(sessions)
    bundle = get_forecast(engine, now=now, fetch=fetch)
    with engine.connect() as conn:
        thresholds = queries.load_thresholds(conn)
    return {
        session.id: conditions.evaluate(
            start=session.starts_at,
            minutes=session.duration_min,
            level=session.level,
            waves=bundle.waves,
            winds=bundle.winds,
            fetched_at=bundle.fetched_at,
            now=now,
            thresholds_by_level=thresholds,
            note=bundle.note,
        )
        for session in sessions
    }


def sunset_for(engine: Engine, day: date) -> datetime | None:
    """Return the saved sunset time (naive UTC) for a Lisbon date, or None.

    Rules: R2.7.
    """
    # Saved days are GMT dates; Lisbon sunset never crosses midnight UTC, so
    # the Lisbon date and the saved date are always the same day.
    with engine.connect() as conn:
        return queries.load_sunset(conn, day)
