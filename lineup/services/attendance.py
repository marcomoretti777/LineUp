"""Roster, attendance marking and roster export. Owner: Member 4 (Credits and reports lane)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Connection, Engine

from lineup import db
from lineup.logic import reports as rules
from lineup.models import Attendance, BookingStatus, Code, Result, Role, SessionView, fill
from lineup.permissions import Action, require
from lineup.queries import reports as q
from lineup.timeutil import fmt_dt, to_local, utcnow

# How far back the roster picker reaches, so recent attendance can be corrected.
ROSTER_LOOKBACK = timedelta(days=7)

ROSTER_HEADER = ("session_start", "student", "email", "level", "status", "attendance")

_ATTENDANCE_LABELS = {Attendance.ATTENDED: "attended", Attendance.NO_SHOW: "a no-show"}


def _not_found() -> Result:
    return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))


def _load_session(conn: Connection, actor_id: int, session_id: int,
                  action: Action) -> tuple[SessionView | None, Result | None]:
    # Shared opening of every roster action: actor, session, then ownership.
    actor = db.get_actor(conn, actor_id)
    if actor is None:
        return None, _not_found()
    session = db.get_session(conn, session_id)
    if session is None:
        return None, _not_found()
    denied = require(actor, action, owner_id=session.instructor_id)
    if denied:
        return None, denied
    return session, None


def _roster_data(conn: Connection, session: SessionView) -> dict:
    booked = q.roster_rows(conn, session.id)
    counts = q.attended_beginner_counts(conn, [r.member_id for r in booked])
    return {
        "session": session,
        "booked": [
            {"booking_id": r.booking_id, "member_id": r.member_id, "name": r.name,
             "email": r.email, "level": r.level,
             "beginner_attended": counts.get(r.member_id, 0), "attendance": r.attendance}
            for r in booked
        ],
        "waitlist": [
            {"entry_id": w.entry_id, "member_id": w.member_id, "name": w.name,
             "email": w.email, "level": w.level, "joined_at": w.joined_at}
            for w in q.waitlist_rows(conn, session.id)
        ],
    }


def roster_sessions(engine: Engine, actor_id: int, now: datetime | None = None) -> Result:
    """List the sessions whose roster the actor may open, from 7 days ago onwards.

    Instructors get their own sessions, admins every session; called-off
    sessions are included so their roster can still be read. data is a list
    of SessionView, earliest start first.

    Rules: section 3 (View roster), section 11 (Roster).
    """
    now = now or utcnow()
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return _not_found()
        # Listing one's own sessions is an "own" read, so the owner is the actor.
        denied = require(actor, Action.VIEW_ROSTER, owner_id=actor.id)
        if denied:
            return denied
        own = None if actor.role == Role.ADMIN else actor.id
        sessions = q.sessions_from(conn, now - ROSTER_LOOKBACK, instructor_id=own)
    return Result.success(f"{len(sessions)} sessions.", sessions)

def roster(engine: Engine, actor_id: int, session_id: int) -> Result:
    """Return a session's booked students and waitlist for its instructor or an admin.

    data is {"session": SessionView, "booked": [...], "waitlist": [...]}: booked
    rows carry name, email, level, attended Beginner count and attendance;
    waitlist rows come first joiner first.

    Rules: section 3 (View roster), R3.6, R4.2, R9.2.
    """
    with engine.begin() as conn:
        session, refused = _load_session(conn, actor_id, session_id, Action.VIEW_ROSTER)
        if refused:
            return refused
        data = _roster_data(conn, session)
    return Result.success(f"Roster for {fmt_dt(session.starts_at)}.", data)


def mark_attendance(engine: Engine, actor_id: int, booking_id: int, value: Attendance | str,
                    now: datetime | None = None) -> Result:
    """Mark a confirmed booking attended or no-show, or correct an earlier mark.

    Only the attendance column changes: a no-show gets no refund and no
    ledger row is written. Saving the same mark again succeeds and writes nothing.

    Rules: R9.1, R9.2, R9.3.
    """
    now = now or utcnow()
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return _not_found()
        booking = q.booking_for_attendance(conn, booking_id)
        if booking is None:
            return _not_found()
        session = db.get_session(conn, booking.session_id)
        if session is None:
            return _not_found()
        denied = require(actor, Action.MARK_ATTENDANCE, owner_id=session.instructor_id)
        if denied:
            return denied
        refused = rules.check_can_mark_attendance(
            session_status=session.status,
            starts_at=session.starts_at,
            now=now,
            called_off_at=q.called_off_at(conn, session.id),
        )
        if refused:
            return refused
        try:
            mark = Attendance(value)
        except ValueError:
            return Result.fail(Code.INVALID, fill(
                Code.INVALID, field="Attendance", problem="unknown value",
                allowed="attended, no_show",
            ))
        if booking.status != BookingStatus.CONFIRMED.value:
            return Result.fail(Code.INVALID, fill(
                Code.INVALID, field="Booking", problem="it is no longer confirmed",
                allowed="confirmed bookings",
            ))
        if booking.attendance != mark.value:
            q.set_attendance(conn, booking.id, mark)
    return Result.success(
        f"Saved: marked {_ATTENDANCE_LABELS[mark]} for {fmt_dt(session.starts_at)}.",
        {"booking_id": booking.id, "attendance": mark.value},
    )


def roster_csv(engine: Engine, actor_id: int, session_id: int) -> Result:
    """Export a session's roster as formula-safe CSV bytes for its instructor or an admin.

    Booked students come first (status confirmed, with any attendance mark),
    then the waitlist (status waiting); only the columns in ROSTER_HEADER.

    Rules: R12.7, R12.8.
    """
    with engine.begin() as conn:
        session, refused = _load_session(conn, actor_id, session_id, Action.EXPORT_ROSTER)
        if refused:
            return refused
        data = _roster_data(conn, session)
    start = to_local(session.starts_at).strftime("%Y-%m-%d %H:%M")
    rows = [
        (start, r["name"], r["email"], r["level"], BookingStatus.CONFIRMED.value,
         r["attendance"])
        for r in data["booked"]
    ] + [
        (start, w["name"], w["email"], w["level"], "waiting", None)
        for w in data["waitlist"]
    ]
    text = rules.to_csv(ROSTER_HEADER, rows)
    return Result.success(
        f"Roster CSV for {fmt_dt(session.starts_at)}: {len(rows)} rows.",
        text.encode("utf-8"),
    )
