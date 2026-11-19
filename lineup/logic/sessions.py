"""Pure rules for creating, editing and deleting surf sessions.

Each check returns None when the action is allowed, or a refused Result
whose code decides what the screen shows. Times arrive as naive UTC; the
08:00 start, the 15-minute step and the 14-day date limit are judged in
Lisbon time, because that is the clock instructors and students use.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from lineup.config import (
    CAPACITY_MAX,
    CAPACITY_MIN,
    DURATIONS,
    EARLIEST_START,
    MAX_DAYS_AHEAD,
    MIN_LEAD,
    START_STEP_MIN,
)
from lineup.models import Code, Level, Result, SessionStatus, fill
from lineup.timeutil import fmt_time, local_date, to_local

_LEVELS = tuple(level.value for level in Level)
_LEAD_HOURS = int(MIN_LEAD.total_seconds() // 3600)
# Labels used in messages; edits are keyed by the same names as the session columns.
_FIELD_LABELS = {
    "starts_at": "Start time",
    "duration_min": "Duration",
    "capacity": "Capacity",
    "level": "Level",
}


def _invalid(field: str, problem: str, allowed: str) -> Result:
    message = fill(Code.INVALID, field=field, problem=problem, allowed=allowed)
    return Result.fail(Code.INVALID, message)


def _check_start_clock(starts_at: datetime) -> Result | None:
    local = to_local(starts_at)
    allowed = f"{EARLIEST_START:%H:%M} or later, every {START_STEP_MIN} minutes"
    off_step = local.minute % START_STEP_MIN or local.second or local.microsecond
    if off_step:
        problem = f"{local:%H:%M} is not on a {START_STEP_MIN}-minute step"
        return _invalid("Start time", problem, allowed)
    if local.time() < EARLIEST_START:
        return _invalid("Start time", f"{local:%H:%M} is before {EARLIEST_START:%H:%M}", allowed)
    return None


def _check_start_window(now: datetime, starts_at: datetime) -> Result | None:
    allowed = (
        f"at least {_LEAD_HOURS} hours from now and at most {MAX_DAYS_AHEAD} days after today"
    )
    if starts_at < now + MIN_LEAD:
        return _invalid("Start time", f"it is less than {_LEAD_HOURS} hours from now", allowed)
    last_day = local_date(now) + timedelta(days=MAX_DAYS_AHEAD)
    day = local_date(starts_at)
    if day > last_day:
        problem = f"{day:%d %b} is more than {MAX_DAYS_AHEAD} days ahead"
        return _invalid("Start time", problem, allowed)
    return None


def _check_duration(duration_min: Any) -> Result | None:
    if isinstance(duration_min, bool) or duration_min not in DURATIONS:
        listed = ", ".join(str(d) for d in DURATIONS[:-1]) + f" or {DURATIONS[-1]} minutes"
        return _invalid("Duration", f"{duration_min} minutes is not offered", listed)
    return None


def _check_capacity(capacity: Any, low: int = CAPACITY_MIN) -> Result | None:
    allowed = f"a whole number from {low} to {CAPACITY_MAX}"
    # bool is a subclass of int, but a tick box value is never a place count.
    if isinstance(capacity, bool) or not isinstance(capacity, int):
        return _invalid("Capacity", f"{capacity!r} is not a whole number", allowed)
    if capacity < low:
        problem = f"{capacity} is below {low}"
        if low > CAPACITY_MIN:
            problem += ", and places can only be added once someone has booked"
        return _invalid("Capacity", problem, allowed)
    if capacity > CAPACITY_MAX:
        return _invalid("Capacity", f"{capacity} is above {CAPACITY_MAX}", allowed)
    return None


def _check_level(level: Any) -> Result | None:
    if not isinstance(level, str) or level not in _LEVELS:
        allowed = " or ".join(value.capitalize() for value in _LEVELS)
        return _invalid("Level", f"{level!r} is not a session level", allowed)
    return None


def _check_latest_end(
    starts_at: datetime, duration_min: int, latest_end: datetime | None
) -> Result | None:
    if latest_end is None:
        return None
    ends_at = starts_at + timedelta(minutes=duration_min)
    if ends_at > latest_end:
        return _invalid(
            "End time",
            f"{fmt_time(ends_at)} is after {fmt_time(latest_end)}",
            f"ending by {fmt_time(latest_end)}",
        )
    return None


def _closed(now: datetime, starts_at: datetime, status: SessionStatus, what: str) -> Result | None:
    # Shared by edit and delete so both close at exactly the same moment (R2.8).
    if status == SessionStatus.CALLED_OFF:
        return Result.fail(
            Code.CLOSED,
            fill(Code.CLOSED, what=f"{what} this called-off session", time=fmt_time(starts_at)),
        )
    if now >= starts_at:
        return Result.fail(Code.CLOSED, fill(Code.CLOSED, what=what, time=fmt_time(starts_at)))
    return None


def _first_refusal(*checks: Result | None) -> Result | None:
    return next((c for c in checks if c is not None), None)


def validate_new_session(
    *,
    now: datetime,
    starts_at: datetime,
    duration_min: Any,
    capacity: Any,
    level: Any,
    latest_end: datetime | None = None,
) -> Result | None:
    """Return the refusal for a new session's fields, or None when every field is allowed.

    Rules: R2.1, R2.2, R2.3, R2.4, R2.5, R2.7.
    """
    refusal = _first_refusal(
        _check_start_clock(starts_at),
        _check_start_window(now, starts_at),
        _check_duration(duration_min),
        _check_capacity(capacity),
        _check_level(level),
    )
    if refusal:
        return refusal
    # Last, because the end time is only meaningful once the duration is valid.
    return _check_latest_end(starts_at, duration_min, latest_end)


def _overlaps(a_start: datetime, a_min: int, b_start: datetime, b_min: int) -> bool:
    a_end = a_start + timedelta(minutes=a_min)
    b_end = b_start + timedelta(minutes=b_min)
    return a_start < b_end and b_start < a_end


def has_overlap(new_start: datetime, new_minutes: int, existing: Iterable[Any]) -> bool:
    """Say whether a new session shares any minute with the instructor's scheduled sessions.

    Rules: R2.6.
    """
    return any(
        _overlaps(new_start, new_minutes, s.starts_at, s.duration_min)
        for s in existing
        if getattr(s, "status", SessionStatus.SCHEDULED) != SessionStatus.CALLED_OFF
    )


def check_edit(
    *,
    now: datetime,
    starts_at: datetime,
    status: SessionStatus,
    confirmed_count: int,
    current: Mapping[str, Any],
    changes: Mapping[str, Any],
    latest_end: datetime | None = None,
) -> Result | None:
    """Return the refusal for editing a session, or None when the changes are allowed.

    Rules: R2.1, R2.2, R2.3, R2.4, R2.5, R2.7, R2.8, R2.9.
    """
    closed = _closed(now, starts_at, status, "editing")
    if closed:
        return closed
    # Edit forms resubmit every field, so only values that differ count as changes.
    changed = {k: v for k, v in changes.items() if current.get(k) != v}

    if confirmed_count > 0:
        for field in ("starts_at", "duration_min", "level"):
            if field in changed:
                return _invalid(
                    _FIELD_LABELS[field],
                    "it can't change once someone has booked",
                    f"raising capacity up to {CAPACITY_MAX}, or calling the session off",
                )
        if "capacity" in changed:
            return _check_capacity(changed["capacity"], low=current["capacity"])
        return None

    merged = {**current, **changed}
    time_changed = "starts_at" in changed or "duration_min" in changed
    # An unchanged start is not re-checked against the 3-hour lead, so a
    # capacity edit shortly before an unbooked session is still possible.
    refusal = _first_refusal(
        _check_start_clock(merged["starts_at"]) if "starts_at" in changed else None,
        _check_start_window(now, merged["starts_at"]) if "starts_at" in changed else None,
        _check_duration(merged["duration_min"]) if "duration_min" in changed else None,
        _check_capacity(merged["capacity"]) if "capacity" in changed else None,
        _check_level(merged["level"]) if "level" in changed else None,
    )
    if refusal:
        return refusal
    if time_changed:
        return _check_latest_end(merged["starts_at"], merged["duration_min"], latest_end)
    return None


def check_delete(
    *,
    now: datetime,
    starts_at: datetime,
    status: SessionStatus,
    ever_booked: bool,
    ever_waited: bool,
) -> Result | None:
    """Return the refusal for deleting a session, or None when nobody ever booked or waited for it.

    Rules: R2.8, R2.11.
    """
    closed = _closed(now, starts_at, status, "deleting")
    if closed:
        return closed
    if ever_booked or ever_waited:
        return _invalid(
            "Session",
            "someone has booked or joined its waitlist",
            "deleting only sessions nobody booked or waited for; call it off instead",
        )
    return None
