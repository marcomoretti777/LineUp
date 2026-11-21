"""Queries the reports lane needs beyond the shared ones in lineup/db.py.

Every function takes an open connection, so the calling service keeps all
its reads and writes in one transaction.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import Connection, Row, func, select, update

from lineup import schema
from lineup.models import (
    Attendance,
    BookingStatus,
    Level,
    RequestStatus,
    SessionStatus,
    SessionView,
    WaitStatus,
)


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


def sessions_from(conn: Connection, since: datetime,
                  instructor_id: int | None = None) -> list[SessionView]:
    """Return sessions starting at or after `since`, called-off ones included, by start.

    With instructor_id, only that instructor's sessions.

    Rules: section 3 (View roster), section 11 (Roster).
    """
    s, m = schema.surf_sessions, schema.members
    query = (
        select(s.c.id, s.c.instructor_id, m.c.full_name.label("instructor_name"),
               s.c.starts_at, s.c.duration_min, s.c.level, s.c.capacity,
               s.c.booked_count, s.c.status)
        .join(m, m.c.id == s.c.instructor_id)
        .where(s.c.starts_at >= since)
        .order_by(s.c.starts_at, s.c.id)
    )
    if instructor_id is not None:
        query = query.where(s.c.instructor_id == instructor_id)
    return [
        SessionView(id=r.id, instructor_id=r.instructor_id, instructor_name=r.instructor_name,
                    starts_at=r.starts_at, duration_min=r.duration_min, level=Level(r.level),
                    capacity=r.capacity, booked_count=r.booked_count,
                    status=SessionStatus(r.status))
        for r in conn.execute(query).all()
    ]


# ---------- reports (R12) ----------
# Periods arrive as a naive UTC range [lo, hi): lo inclusive, hi exclusive.

def sessions_run(conn: Connection, lo: datetime, hi: datetime, now: datetime) -> list[Row]:
    """Return sessions starting in [lo, hi) that were not called off and ended by `now`.

    Rows have id, level, capacity and booked_count. The end time is checked in
    Python because adding minutes to a timestamp differs between SQLite and Postgres.

    Rules: R12.2.
    """
    s = schema.surf_sessions
    rows = conn.execute(
        select(s.c.id, s.c.level, s.c.capacity, s.c.booked_count, s.c.starts_at,
               s.c.duration_min)
        .where(s.c.starts_at >= lo, s.c.starts_at < hi, s.c.starts_at < now,
               s.c.status == SessionStatus.SCHEDULED.value)
        .order_by(s.c.starts_at, s.c.id)
    ).all()
    return [r for r in rows if r.starts_at + timedelta(minutes=r.duration_min) <= now]


def attendance_marks(conn: Connection, session_ids: Iterable[int]) -> list[str | None]:
    """Return the attendance value of every confirmed booking in the given sessions.

    Rules: R12.4.
    """
    ids = list(session_ids)
    if not ids:
        return []
    b = schema.bookings
    return list(conn.execute(
        select(b.c.attendance).where(b.c.session_id.in_(ids),
                                     b.c.status == BookingStatus.CONFIRMED.value)
    ).scalars())


def approved_requests(conn: Connection, lo: datetime, hi: datetime) -> list[Row]:
    """Return requests approved in [lo, hi) with their pack's credits and price_cents.

    Rules: R12.5.
    """
    r, p = schema.credit_requests, schema.credit_packs
    return conn.execute(
        select(r.c.id, p.c.credits, p.c.price_cents)
        .join(p, p.c.id == r.c.pack_id)
        .where(r.c.status == RequestStatus.APPROVED.value,
               r.c.decided_at >= lo, r.c.decided_at < hi)
    ).all()


def calloff_categories(conn: Connection, lo: datetime, hi: datetime) -> list[str | None]:
    """Return the call-off category of every called-off session starting in [lo, hi).

    Rules: R12.6.
    """
    s = schema.surf_sessions
    return list(conn.execute(
        select(s.c.call_off_category).where(
            s.c.status == SessionStatus.CALLED_OFF.value, s.c.starts_at >= lo, s.c.starts_at < hi,
        )
    ).scalars())


def confirmed_booking_starts(conn: Connection, lo: datetime, hi: datetime) -> list[datetime]:
    """Return the session start of every confirmed booking whose session starts in [lo, hi).

    Rules: R12.3 (bookings chart).
    """
    b, s = schema.bookings, schema.surf_sessions
    return list(conn.execute(
        select(s.c.starts_at).join(b, b.c.session_id == s.c.id)
        .where(b.c.status == BookingStatus.CONFIRMED.value,
               s.c.starts_at >= lo, s.c.starts_at < hi)
    ).scalars())


def bookings_export_rows(conn: Connection, lo: datetime, hi: datetime) -> list[Row]:
    """Return every booking whose session starts in [lo, hi), for the bookings CSV.

    Rows have starts_at, level, instructor, student_email, status, attendance
    and refunded, by session start and then booking id.

    Rules: R12.7.
    """
    b, s = schema.bookings, schema.surf_sessions
    student, instructor = schema.members.alias("student"), schema.members.alias("instructor")
    return conn.execute(
        select(s.c.starts_at, s.c.level, instructor.c.full_name.label("instructor"),
               student.c.email.label("student_email"), b.c.status, b.c.attendance,
               b.c.refunded)
        .join(s, s.c.id == b.c.session_id)
        .join(student, student.c.id == b.c.member_id)
        .join(instructor, instructor.c.id == s.c.instructor_id)
        .where(s.c.starts_at >= lo, s.c.starts_at < hi)
        .order_by(s.c.starts_at, b.c.id)
    ).all()


def ledger_export_rows(conn: Connection, lo: datetime, hi: datetime) -> list[Row]:
    """Return ledger rows created in [lo, hi) with the member's email, oldest first.

    Rules: R10.8, R12.7.
    """
    lg, m = schema.credit_ledger, schema.members
    return conn.execute(
        select(lg.c.created_at, m.c.email.label("member_email"), lg.c.delta, lg.c.kind,
               lg.c.ref)
        .join(m, m.c.id == lg.c.member_id)
        .where(lg.c.created_at >= lo, lg.c.created_at < hi)
        .order_by(lg.c.created_at, lg.c.id)
    ).all()


def requests_export_rows(conn: Connection, lo: datetime, hi: datetime) -> list[Row]:
    """Return credit requests created in [lo, hi) with member email and pack details, oldest first.

    Rules: R10.5, R12.7.
    """
    r, p, m = schema.credit_requests, schema.credit_packs, schema.members
    return conn.execute(
        select(r.c.created_at, m.c.email.label("member_email"), p.c.name.label("pack"),
               p.c.credits, p.c.price_cents, r.c.status, r.c.decided_at, r.c.decision_note)
        .join(p, p.c.id == r.c.pack_id)
        .join(m, m.c.id == r.c.member_id)
        .where(r.c.created_at >= lo, r.c.created_at < hi)
        .order_by(r.c.created_at, r.c.id)
    ).all()
