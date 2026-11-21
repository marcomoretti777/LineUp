"""Queries the forecast lane needs: saved forecast rows, thresholds and app settings.

Every function takes an open connection, so the calling service decides
where each transaction starts and ends.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import Connection, delete, func, insert, select, update

from lineup import schema
from lineup.openmeteo import DaySunset, HourValue

Thresholds = tuple[float, float, float, float]


def newest_fetch_time(conn: Connection) -> datetime | None:
    """Return the fetch time of the newest saved forecast hour, or None if none is saved.

    Rules: R7.1, R6.4.
    """
    return conn.execute(select(func.max(schema.forecast_hours.c.fetched_at))).scalar()


def save_hours(conn: Connection, waves: Iterable[HourValue], winds: Iterable[HourValue],
               fetched_at: datetime) -> None:
    """Save hourly waves and wind, replacing any saved rows for the same hours.

    Rules: R7.3.
    """
    rows: dict[datetime, dict] = {}
    for wave in waves:
        rows.setdefault(wave.hour_utc, _empty_hour(wave.hour_utc, fetched_at))
        rows[wave.hour_utc]["wave_height_m"] = wave.value
    for wind in winds:
        rows.setdefault(wind.hour_utc, _empty_hour(wind.hour_utc, fetched_at))
        rows[wind.hour_utc]["wind_speed_kmh"] = wind.value
    if not rows:
        return
    table = schema.forecast_hours
    conn.execute(delete(table).where(table.c.hour_utc.in_(list(rows))))
    conn.execute(insert(table), list(rows.values()))


def _empty_hour(hour: datetime, fetched_at: datetime) -> dict:
    return {"hour_utc": hour, "wave_height_m": None, "wind_speed_kmh": None,
            "fetched_at": fetched_at}


def save_days(conn: Connection, sunsets: Iterable[DaySunset], fetched_at: datetime) -> None:
    """Save one sunset per day, replacing any saved rows for the same days.

    Rules: R7.3.
    """
    rows = {
        sunset.day: {"day": sunset.day, "sunset_utc": sunset.sunset_utc, "fetched_at": fetched_at}
        for sunset in sunsets
    }
    if not rows:
        return
    table = schema.forecast_days
    conn.execute(delete(table).where(table.c.day.in_(list(rows))))
    conn.execute(insert(table), list(rows.values()))


def load_hours(conn: Connection, start: datetime, end: datetime
               ) -> tuple[dict[datetime, float | None], dict[datetime, float | None]]:
    """Return saved wave and wind maps keyed by hour, for hours in [start, end).

    Rules: R6.1, R7.4.
    """
    table = schema.forecast_hours
    rows = conn.execute(
        select(table.c.hour_utc, table.c.wave_height_m, table.c.wind_speed_kmh)
        .where(table.c.hour_utc >= start, table.c.hour_utc < end)
    ).all()
    waves = {row.hour_utc: row.wave_height_m for row in rows}
    winds = {row.hour_utc: row.wind_speed_kmh for row in rows}
    return waves, winds


def load_sunsets(conn: Connection, start: date, end: date) -> dict[date, datetime | None]:
    """Return saved sunsets keyed by day, for days in [start, end].

    Rules: R2.7.
    """
    table = schema.forecast_days
    rows = conn.execute(
        select(table.c.day, table.c.sunset_utc).where(table.c.day >= start, table.c.day <= end)
    ).all()
    return {row.day: row.sunset_utc for row in rows}


def load_sunset(conn: Connection, day: date) -> datetime | None:
    """Return the saved sunset (naive UTC) for one day, or None if none is saved.

    Rules: R2.7.
    """
    table = schema.forecast_days
    return conn.execute(select(table.c.sunset_utc).where(table.c.day == day)).scalar()


def load_thresholds(conn: Connection) -> dict[str, Thresholds]:
    """Return each level's (go wave, go wind, marginal wave, marginal wind) thresholds.

    Rules: R6.3, R6.6.
    """
    table = schema.condition_thresholds
    rows = conn.execute(
        select(table.c.level, table.c.go_wave_m, table.c.go_wind_kmh,
               table.c.marginal_wave_m, table.c.marginal_wind_kmh)
    ).all()
    return {
        row.level: (row.go_wave_m, row.go_wind_kmh, row.marginal_wave_m, row.marginal_wind_kmh)
        for row in rows
    }


def get_setting(conn: Connection, key: str) -> str | None:
    """Return one app setting's value, or None if it was never set.

    Rules: R7.5, R7.6.
    """
    table = schema.app_settings
    return conn.execute(select(table.c.value).where(table.c.key == key)).scalar()


def set_setting(conn: Connection, key: str, value: str | None, now: datetime) -> None:
    """Create or overwrite one app setting.

    Rules: R7.5, R7.6.
    """
    table = schema.app_settings
    # Update-then-insert works the same on SQLite and Postgres, unlike dialect upserts.
    changed = conn.execute(
        update(table).where(table.c.key == key).values(value=value, updated_at=now)
    ).rowcount
    if not changed:
        conn.execute(insert(table).values(key=key, value=value, updated_at=now))
