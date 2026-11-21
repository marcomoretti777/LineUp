"""Queries the sessions lane needs beyond the shared ones in lineup/db.py.

Every function takes an open connection, so the calling service keeps all
its reads and writes in one transaction.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from lineup import schema
from lineup.models import BookingStatus, Level, SessionStatus, SessionView, WaitStatus

# Only these columns may be changed by an edit; status changes go through call-off.
_UPDATABLE = frozenset({"starts_at", "duration_min", "capacity", "level"})


def instructor_sessions(conn: Connection, instructor_id: int, start: datetime,
                        end: datetime) -> list[SessionView]:
    """Return an instructor's sessions starting in [start, end), any status, earliest first.

    Rules: R2.6, section 11 (My sessions).
    """
    s, m = schema.surf_sessions, schema.members
    rows = conn.execute(
        select(
            s.c.id, s.c.instructor_id, m.c.full_name.label("instructor_name"), s.c.starts_at,
            s.c.duration_min, s.c.level, s.c.capacity, s.c.booked_count, s.c.status,
        )
        .join(m, m.c.id == s.c.instructor_id)
        .where(s.c.instructor_id == instructor_id, s.c.starts_at >= start, s.c.starts_at < end)
        .order_by(s.c.starts_at, s.c.id)
    ).all()
    return [
        SessionView(
            id=r.id, instructor_id=r.instructor_id, instructor_name=r.instructor_name,
            starts_at=r.starts_at, duration_min=r.duration_min, level=Level(r.level),
            capacity=r.capacity, booked_count=r.booked_count, status=SessionStatus(r.status),
        )
        for r in rows
    ]


def insert_session(conn: Connection, instructor_id: int, starts_at: datetime, duration_min: int,
                   capacity: int, level: str) -> int:
    """Insert a scheduled session with no bookings and return its id.

    Rules: R2.1-R2.5.
    """
    return conn.execute(
        insert(schema.surf_sessions).values(
            instructor_id=instructor_id, starts_at=starts_at, duration_min=duration_min,
            capacity=capacity, level=str(level), booked_count=0,
            status=SessionStatus.SCHEDULED.value,
        )
    ).inserted_primary_key[0]


def update_session(conn: Connection, session_id: int, values: Mapping[str, Any]) -> None:
    """Write changed fields of a session; only start, duration, capacity and level are accepted.

    Rules: R2.9.
    """
    unknown = set(values) - _UPDATABLE
    if unknown:
        # A programming error, not user input: services filter fields first.
        raise ValueError(f"not an editable session column: {sorted(unknown)}")
    if not values:
        return
    s = schema.surf_sessions
    conn.execute(update(s).where(s.c.id == session_id).values(**dict(values)))


def delete_session(conn: Connection, session_id: int) -> None:
    """Delete a session row.

    Rules: R2.11.
    """
    s = schema.surf_sessions
    conn.execute(delete(s).where(s.c.id == session_id))


def history_flags(conn: Connection, session_id: int) -> tuple[bool, bool]:
    """Say whether anyone ever booked the session, and whether anyone ever joined its waitlist.

    Any row counts, whatever its status, because a cancelled booking still
    has ledger history that a delete would orphan.

    Rules: R2.11.
    """
    b, w = schema.bookings, schema.waitlist_entries
    ever_booked = conn.execute(
        select(b.c.id).where(b.c.session_id == session_id).limit(1)
    ).first() is not None
    ever_waited = conn.execute(
        select(w.c.id).where(w.c.session_id == session_id).limit(1)
    ).first() is not None
    return ever_booked, ever_waited


def mark_called_off(conn: Connection, session_id: int, category: str, reason: str,
                    now: datetime) -> bool:
    """Mark a scheduled session called off with its category and reason; False if it wasn't scheduled.

    Guarded by the status, so of two concurrent call-offs only one changes the row.

    Rules: R8.2, R8.3, R8.5.
    """
    s = schema.surf_sessions
    result = conn.execute(
        update(s)
        .where(s.c.id == session_id, s.c.status == SessionStatus.SCHEDULED.value)
        .values(
            status=SessionStatus.CALLED_OFF.value, call_off_category=category,
            call_off_reason=reason, called_off_at=now, booked_count=0,
        )
    )
    return result.rowcount == 1


def confirmed_bookings(conn: Connection, session_id: int) -> list[tuple[int, int]]:
    """Return (booking id, member id) for each confirmed booking of a session.

    Rules: R8.3.
    """
    b = schema.bookings
    rows = conn.execute(
        select(b.c.id, b.c.member_id)
        .where(b.c.session_id == session_id, b.c.status == BookingStatus.CONFIRMED.value)
        .order_by(b.c.id)
    ).all()
    return [(r.id, r.member_id) for r in rows]


def call_off_bookings(conn: Connection, session_id: int, now: datetime) -> None:
    """Turn every confirmed booking of a session into called_off.

    Rules: R8.3.
    """
    b = schema.bookings
    conn.execute(
        update(b)
        .where(b.c.session_id == session_id, b.c.status == BookingStatus.CONFIRMED.value)
        .values(status=BookingStatus.CALLED_OFF.value, cancelled_at=now)
    )


def mark_refunded(conn: Connection, booking_id: int) -> None:
    """Flag a booking as refunded, matching its refund:<id> ledger row.

    Rules: R8.3, R10.8.
    """
    b = schema.bookings
    conn.execute(update(b).where(b.c.id == booking_id).values(refunded=True))


def waiting_members(conn: Connection, session_id: int) -> list[tuple[int, int]]:
    """Return (entry id, member id) for each waiting entry of a session.

    Rules: R8.4.
    """
    w = schema.waitlist_entries
    rows = conn.execute(
        select(w.c.id, w.c.member_id)
        .where(w.c.session_id == session_id, w.c.status == WaitStatus.WAITING.value)
        .order_by(w.c.created_at, w.c.id)
    ).all()
    return [(r.id, r.member_id) for r in rows]


def clear_waitlist(conn: Connection, session_id: int, now: datetime) -> None:
    """Mark every waiting entry of a session cleared.

    Rules: R8.4.
    """
    w = schema.waitlist_entries
    conn.execute(
        update(w)
        .where(w.c.session_id == session_id, w.c.status == WaitStatus.WAITING.value)
        .values(status=WaitStatus.CLEARED.value, reason="session called off", updated_at=now)
    )
