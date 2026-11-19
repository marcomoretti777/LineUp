"""Conversion between database time (naive UTC) and screen time (Lisbon).

The database stores naive UTC datetimes; screens show Europe/Lisbon. A
naive datetime passed in here is always read as UTC.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from lineup.config import TIMEZONE

LISBON = ZoneInfo(TIMEZONE)

# Fixed English names: strftime's %a and %b follow the machine locale, which
# would change the text on a Portuguese laptop.
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def utcnow() -> datetime:
    """Return the current time as a naive UTC datetime.

    Rules: section 8 (time convention).
    """
    return datetime.now(UTC).replace(tzinfo=None)


def to_local(dt: datetime) -> datetime:
    """Convert a database datetime to an aware Europe/Lisbon datetime.

    Rules: section 8 (time convention).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(LISBON)


def from_local(day: date, clock: time) -> datetime:
    """Turn a Lisbon date and clock time into a naive UTC datetime.

    Rules: section 8 (time convention).
    """
    local = datetime.combine(day, clock, tzinfo=LISBON)
    return local.astimezone(UTC).replace(tzinfo=None)


def local_date(dt: datetime) -> date:
    """Return the Lisbon calendar date of a database datetime.

    Rules: section 8, R2.2.
    """
    return to_local(dt).date()


def floor_hour(dt: datetime) -> datetime:
    """Drop minutes, seconds and microseconds, keeping the time zone as given.

    Rules: R6.1.
    """
    return dt.replace(minute=0, second=0, microsecond=0)


def fmt_dt(dt: datetime) -> str:
    """Format a database datetime for screens, such as "Fri 20 Nov, 10:00".

    Rules: section 11 (times on every screen).
    """
    local = to_local(dt)
    weekday = _WEEKDAYS[local.weekday()]
    month = _MONTHS[local.month - 1]
    return f"{weekday} {local.day} {month}, {local:%H:%M}"


def fmt_time(dt: datetime) -> str:
    """Format a database datetime as Lisbon "HH:MM".

    Rules: section 11 (times on every screen).
    """
    return f"{to_local(dt):%H:%M}"
