"""Queries the booking lane needs beyond the shared ones in lineup/db.py.

Every function takes an open connection, so the calling service keeps all
its reads and writes in one transaction.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import Connection, Row, insert, select, update

from lineup import schema
from lineup.models import BookingStatus, SessionStatus, WaitStatus


def confirmed_bookings_for_member(conn: Connection, member_id: int) -> list[Row]:
    """Return a member's confirmed bookings with each session's start and duration.

    Rows have id, session_id, starts_at and duration_min, earliest start first.

    Rules: R3.5.
    """
    b, s = schema.bookings, schema.surf_sessions
    return conn.execute(
        select(b.c.id, b.c.session_id, s.c.starts_at, s.c.duration_min)
        .join(s, s.c.id == b.c.session_id)
        .where(b.c.member_id == member_id, b.c.status == BookingStatus.CONFIRMED.value)
        .order_by(s.c.starts_at, b.c.id)
    ).all()


def has_confirmed_booking(conn: Connection, member_id: int, session_id: int) -> bool:
    """Say whether a member already holds a confirmed booking for a session.

    Rules: R3.7.
    """
    b = schema.bookings
    return conn.execute(
        select(b.c.id).where(
            b.c.member_id == member_id,
            b.c.session_id == session_id,
            b.c.status == BookingStatus.CONFIRMED.value,
        )
    ).first() is not None


def confirmed_session_ids(conn: Connection, member_id: int,
                          session_ids: Iterable[int]) -> set[int]:
    """Return which of the given sessions a member holds a confirmed booking for.

    Rules: R3.7.
    """
    b = schema.bookings
    return set(
        conn.execute(
            select(b.c.session_id).where(
                b.c.member_id == member_id,
                b.c.session_id.in_(list(session_ids)),
                b.c.status == BookingStatus.CONFIRMED.value,
            )
        ).scalars()
    )


def waiting_entries_for_sessions(conn: Connection, session_ids: Iterable[int]) -> list[Row]:
    """Return the waiting entries of several sessions with id, session_id, member_id, joined_at.

    One query for a whole page of sessions; joined_at is named as in
    waiting_entries so logic.booking.promotion_order can sort the rows.

    Rules: R4.2, R4.6.
    """
    w = schema.waitlist_entries
    return conn.execute(
        select(w.c.id, w.c.session_id, w.c.member_id, w.c.created_at.label("joined_at")).where(
            w.c.session_id.in_(list(session_ids)), w.c.status == WaitStatus.WAITING.value
        )
    ).all()


def waiting_entry(conn: Connection, member_id: int, session_id: int) -> int | None:
    """Return the id of a member's waiting entry for a session, or None.

    Rules: R3.9.
    """
    w = schema.waitlist_entries
    return conn.execute(
        select(w.c.id).where(
            w.c.member_id == member_id,
            w.c.session_id == session_id,
            w.c.status == WaitStatus.WAITING.value,
        )
    ).scalar_one_or_none()


def reserve_place(conn: Connection, session_id: int) -> bool:
    """Take one place in a scheduled session in a single UPDATE; False if none was left.

    One statement, so the database decides who gets the last place: two
    concurrent bookings can never both see a free place and overfill it.

    Rules: R3.8.
    """
    s = schema.surf_sessions
    result = conn.execute(
        update(s)
        .where(
            s.c.id == session_id,
            s.c.status == SessionStatus.SCHEDULED.value,
            s.c.booked_count < s.c.capacity,
        )
        .values(booked_count=s.c.booked_count + 1)
    )
    return result.rowcount == 1


def insert_booking(conn: Connection, session_id: int, member_id: int, now: datetime) -> int:
    """Insert a confirmed booking and return its id.

    Rules: R3.7, R3.8.
    """
    return conn.execute(
        insert(schema.bookings).values(
            session_id=session_id,
            member_id=member_id,
            status=BookingStatus.CONFIRMED.value,
            created_at=now,
        )
    ).inserted_primary_key[0]


def get_booking(conn: Connection, booking_id: int) -> Row | None:
    """Return a booking with its session's start, or None if it does not exist.

    The row has id, session_id, member_id, status, refunded, cancelled_at and starts_at.

    Rules: R5.1.
    """
    b, s = schema.bookings, schema.surf_sessions
    return conn.execute(
        select(b.c.id, b.c.session_id, b.c.member_id, b.c.status, b.c.refunded,
               b.c.cancelled_at, s.c.starts_at)
        .join(s, s.c.id == b.c.session_id)
        .where(b.c.id == booking_id)
    ).first()


def set_booking_cancelled(conn: Connection, booking_id: int, now: datetime) -> bool:
    """Cancel a confirmed booking in a single UPDATE; False if it was no longer confirmed.

    Only one of two concurrent cancels can match the status guard, so a place
    is never released twice.

    Rules: R5.1, R5.4.
    """
    b = schema.bookings
    result = conn.execute(
        update(b)
        .where(b.c.id == booking_id, b.c.status == BookingStatus.CONFIRMED.value)
        .values(status=BookingStatus.CANCELLED.value, cancelled_at=now)
    )
    return result.rowcount == 1


def release_place(conn: Connection, session_id: int) -> None:
    """Give one place back to a session, never taking booked_count below 0.

    Rules: R5.3.
    """
    s = schema.surf_sessions
    conn.execute(
        update(s)
        .where(s.c.id == session_id, s.c.booked_count > 0)
        .values(booked_count=s.c.booked_count - 1)
    )


def mark_refunded(conn: Connection, booking_id: int) -> None:
    """Record that a booking's credit was refunded.

    Rules: R5.2.
    """
    b = schema.bookings
    conn.execute(update(b).where(b.c.id == booking_id).values(refunded=True))


def set_wait_status(conn: Connection, entry_id: int, status: WaitStatus, reason: str | None,
                    now: datetime) -> None:
    """Move a waitlist entry to a new status, recording why and when.

    Rules: R3.9, R4.3.
    """
    w = schema.waitlist_entries
    conn.execute(
        update(w)
        .where(w.c.id == entry_id)
        .values(status=WaitStatus(status).value, reason=reason, updated_at=now)
    )


def waiting_entries(conn: Connection, session_id: int) -> list[Row]:
    """Return a session's waiting entries with id, member_id and joined_at.

    joined_at is the entry's created_at, named so logic.booking.promotion_order
    can sort the rows directly.

    Rules: R4.2, R4.6.
    """
    w = schema.waitlist_entries
    return conn.execute(
        select(w.c.id, w.c.member_id, w.c.created_at.label("joined_at")).where(
            w.c.session_id == session_id, w.c.status == WaitStatus.WAITING.value
        )
    ).all()


def insert_waiting_entry(conn: Connection, session_id: int, member_id: int,
                         now: datetime) -> int:
    """Insert a waiting entry joined at `now` and return its id.

    Rules: R4.1, R4.2.
    """
    return conn.execute(
        insert(schema.waitlist_entries).values(
            session_id=session_id,
            member_id=member_id,
            status=WaitStatus.WAITING.value,
            created_at=now,
            updated_at=now,
        )
    ).inserted_primary_key[0]


def get_wait_entry(conn: Connection, entry_id: int) -> Row | None:
    """Return a waitlist entry with its session's start, or None if it does not exist.

    The row has id, session_id, member_id, status and starts_at.

    Rules: R4.5.
    """
    w, s = schema.waitlist_entries, schema.surf_sessions
    return conn.execute(
        select(w.c.id, w.c.session_id, w.c.member_id, w.c.status, s.c.starts_at)
        .join(s, s.c.id == w.c.session_id)
        .where(w.c.id == entry_id)
    ).first()


def leave_entry(conn: Connection, entry_id: int, now: datetime) -> bool:
    """Mark a waiting entry as left in a single UPDATE; False if it was no longer waiting.

    The status guard stops a leave from overwriting a promotion that won the race.

    Rules: R4.5.
    """
    w = schema.waitlist_entries
    result = conn.execute(
        update(w)
        .where(w.c.id == entry_id, w.c.status == WaitStatus.WAITING.value)
        .values(status=WaitStatus.LEFT.value, updated_at=now)
    )
    return result.rowcount == 1


def _session_columns():
    # Named like SessionView's fields, so the service builds the view from any row.
    s, m = schema.surf_sessions, schema.members
    return (
        s.c.id, s.c.instructor_id, m.c.full_name.label("instructor_name"), s.c.starts_at,
        s.c.duration_min, s.c.level, s.c.capacity, s.c.booked_count, s.c.status,
    )


def member_bookings(conn: Connection, member_id: int) -> list[Row]:
    """Return every booking of one member with its session and instructor's name.

    Rows have booking_id, booking_status, attendance and refunded, plus the
    SessionView fields (id is the session's id), earliest start first.

    Rules: LU06.
    """
    b, s, m = schema.bookings, schema.surf_sessions, schema.members
    return conn.execute(
        select(
            b.c.id.label("booking_id"), b.c.status.label("booking_status"),
            b.c.attendance, b.c.refunded, *_session_columns(),
        )
        .join(s, s.c.id == b.c.session_id)
        .join(m, m.c.id == s.c.instructor_id)
        .where(b.c.member_id == member_id)
        .order_by(s.c.starts_at, b.c.id)
    ).all()


def member_waiting_entries(conn: Connection, member_id: int, now: datetime) -> list[Row]:
    """Return one member's waiting entries for sessions that start after now.

    Rows have entry_id plus the SessionView fields, earliest start first.

    Rules: R4.5, R4.6.
    """
    w, s, m = schema.waitlist_entries, schema.surf_sessions, schema.members
    return conn.execute(
        select(w.c.id.label("entry_id"), *_session_columns())
        .join(s, s.c.id == w.c.session_id)
        .join(m, m.c.id == s.c.instructor_id)
        .where(
            w.c.member_id == member_id,
            w.c.status == WaitStatus.WAITING.value,
            s.c.starts_at > now,
        )
        .order_by(s.c.starts_at, w.c.id)
    ).all()
