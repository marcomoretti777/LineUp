"""Queries the reports lane needs beyond the shared ones in lineup/db.py.

Every function takes an open connection, so the calling service keeps all
its reads and writes in one transaction.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import Connection, Row, func, select, update

from lineup import schema
from lineup.models import Attendance, BookingStatus, Level, WaitStatus


def booking_for_attendance(conn: Connection, booking_id: int) -> Row | None:
    """Return a booking's id, session_id, member_id, status and attendance, or None.

    Rules: R9.1, R9.2.
    """
    b = schema.bookings
    return conn.execute(
        select(b.c.id, b.c.session_id, b.c.member_id, b.c.status, b.c.attendance)
        .where(b.c.id == booking_id)
    ).first()


def set_attendance(conn: Connection, booking_id: int, value: Attendance) -> None:
    """Store an attendance mark on a booking; only the attendance column changes.

    Rules: R9.2, R9.3.
    """
    b = schema.bookings
    conn.execute(update(b).where(b.c.id == booking_id).values(attendance=Attendance(value).value))


def called_off_at(conn: Connection, session_id: int) -> datetime | None:
    """Return when a session was called off, or None if it never was.

    Rules: R9.1.
    """
    s = schema.surf_sessions
    return conn.execute(select(s.c.called_off_at).where(s.c.id == session_id)).scalar_one_or_none()


def roster_rows(conn: Connection, session_id: int) -> list[Row]:
    """Return a session's confirmed bookings with the student's details, by name.

    Rows have booking_id, member_id, name, email, level and attendance.

    Rules: R9.2, section 11 (Roster).
    """
    b, m = schema.bookings, schema.members
    return conn.execute(
        select(b.c.id.label("booking_id"), m.c.id.label("member_id"),
               m.c.full_name.label("name"), m.c.email, m.c.level, b.c.attendance)
        .join(m, m.c.id == b.c.member_id)
        .where(b.c.session_id == session_id, b.c.status == BookingStatus.CONFIRMED.value)
        .order_by(m.c.full_name, b.c.id)
    ).all()


def waitlist_rows(conn: Connection, session_id: int) -> list[Row]:
    """Return a session's waiting entries with the student's details, first joiner first.

    Rows have entry_id, member_id, name, email, level and joined_at; ties in
    joined_at are broken by id, as in the promotion order of R4.2.

    Rules: R4.2, section 11 (Roster).
    """
    w, m = schema.waitlist_entries, schema.members
    return conn.execute(
        select(w.c.id.label("entry_id"), m.c.id.label("member_id"),
               m.c.full_name.label("name"), m.c.email, m.c.level,
               w.c.created_at.label("joined_at"))
        .join(m, m.c.id == w.c.member_id)
        .where(w.c.session_id == session_id, w.c.status == WaitStatus.WAITING.value)
        .order_by(w.c.created_at, w.c.id)
    ).all()


def attended_beginner_counts(conn: Connection, member_ids: Iterable[int]) -> dict[int, int]:
    """Return how many Beginner sessions each member attended; members with none are left out.

    One query for the whole roster instead of one per student.

    Rules: R3.6, section 11 (Roster).
    """
    ids = list(member_ids)
    if not ids:
        return {}
    b, s = schema.bookings, schema.surf_sessions
    rows = conn.execute(
        select(b.c.member_id, func.count(b.c.id))
        .join(s, s.c.id == b.c.session_id)
        .where(
            b.c.member_id.in_(ids),
            b.c.status == BookingStatus.CONFIRMED.value,
            b.c.attendance == Attendance.ATTENDED.value,
            s.c.level == Level.BEGINNER.value,
        )
        .group_by(b.c.member_id)
    ).all()
    return {member_id: count for member_id, count in rows}
