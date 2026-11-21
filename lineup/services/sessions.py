"""Session actions. Owner: Member 3 (Sessions and forecast lane).

Instructors create, edit, delete and list their own sessions here. Every
action follows the contract's service pattern: load the actor, check the
permission, ask the pure rule in lineup/logic/sessions.py, then write in
one transaction. call_off stays the F03 stub until task S06.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Connection, Engine

from lineup import db
from lineup.config import DURATIONS, MAX_DAYS_AHEAD
from lineup.logic import sessions as rules
from lineup.models import MESSAGES, Code, Result, SessionView, fill
from lineup.permissions import Action, require
from lineup.queries import sessions as q

# Imported as a module so tests can replace promote_waitlist with a spy.
from lineup.services import booking
from lineup.timeutil import fmt_dt, from_local, local_date, to_local, utcnow

_EDITABLE = ("day", "start_time", "duration_min", "capacity", "level")


def _not_found() -> Result:
    return Result.fail(Code.NOT_FOUND, MESSAGES[Code.NOT_FOUND])


def _clash(conn: Connection, instructor_id: int, starts_at: datetime, duration_min: int,
           exclude_id: int | None = None) -> Result | None:
    # Look back by the longest duration so a session that started earlier
    # but is still running at starts_at is found too.
    window_start = starts_at - timedelta(minutes=max(DURATIONS))
    window_end = starts_at + timedelta(minutes=duration_min)
    for existing in q.instructor_sessions(conn, instructor_id, window_start, window_end):
        if existing.id != exclude_id and rules.has_overlap(starts_at, duration_min, [existing]):
            return Result.fail(Code.CLASH, fill(Code.CLASH, time=fmt_dt(existing.starts_at)))
    return None


def _load_owned(conn: Connection, actor_id: int,
                session_id: int) -> tuple[SessionView | None, Result | None]:
    actor = db.get_actor(conn, actor_id)
    if actor is None:
        return None, _not_found()
    session = db.get_session(conn, session_id)
    if session is None:
        # Check the role first, so a student never learns which ids exist.
        return None, require(actor, Action.MANAGE_OWN_SESSIONS, owner_id=actor.id) or _not_found()
    denied = require(actor, Action.MANAGE_OWN_SESSIONS, owner_id=session.instructor_id)
    return (None, denied) if denied else (session, None)


def create_session(engine: Engine, actor_id: int, day: date, start_time: time,
                   duration_min: int, capacity: int, level: str,
                   now: datetime | None = None) -> Result:
    """Create a scheduled session for the acting instructor from a Lisbon date and start time.

    Rules: R2.1, R2.2, R2.3, R2.4, R2.5, R2.6, section 3 (MANAGE_OWN_SESSIONS).
    """
    now = now or utcnow()
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return _not_found()
        denied = require(actor, Action.MANAGE_OWN_SESSIONS, owner_id=actor.id)
        if denied:
            return denied

        starts_at = from_local(day, start_time)
        # The sunset limit (R2.7) is wired in task S08.
        refusal = rules.validate_new_session(
            now=now, starts_at=starts_at, duration_min=duration_min,
            capacity=capacity, level=level, latest_end=None,
        ) or _clash(conn, actor.id, starts_at, duration_min)
        if refusal:
            return refusal

        session_id = q.insert_session(conn, actor.id, starts_at, duration_min, capacity, level)
        return Result.success(
            f"Session created: {fmt_dt(starts_at)}, {duration_min} min, {capacity} places.",
            {"session_id": session_id},
        )


def edit_session(engine: Engine, actor_id: int, session_id: int, changes: Mapping[str, Any],
                 now: datetime | None = None) -> Result:
    """Change an instructor's own session; keys are day, start_time, duration_min, capacity, level.

    Rules: R2.1-R2.6, R2.8, R2.9, R2.10, section 3 (MANAGE_OWN_SESSIONS).
    """
    now = now or utcnow()
    with engine.begin() as conn:
        session, refusal = _load_owned(conn, actor_id, session_id)
        if refusal:
            return refusal

        unknown = sorted(set(changes) - set(_EDITABLE))
        if unknown:
            return Result.fail(Code.INVALID, fill(
                Code.INVALID, field="Change", problem=f"{', '.join(unknown)} can't be edited",
                allowed="day, start time, duration, capacity or level",
            ))

        current = {
            "starts_at": session.starts_at, "duration_min": session.duration_min,
            "capacity": session.capacity, "level": session.level.value,
        }
        proposed = {k: changes[k] for k in ("duration_min", "capacity", "level") if k in changes}
        if "day" in changes or "start_time" in changes:
            local = to_local(session.starts_at)
            proposed["starts_at"] = from_local(
                changes.get("day", local.date()), changes.get("start_time", local.time())
            )

        refusal = rules.check_edit(
            now=now, starts_at=session.starts_at, status=session.status,
            confirmed_count=session.booked_count, current=current, changes=proposed,
            latest_end=None,
        )
        if refusal:
            return refusal

        changed = {k: v for k, v in proposed.items() if current[k] != v}
        merged = {**current, **changed}
        if "starts_at" in changed or "duration_min" in changed:
            clash = _clash(conn, session.instructor_id, merged["starts_at"],
                           merged["duration_min"], exclude_id=session.id)
            if clash:
                return clash

        q.update_session(conn, session.id, changed)
        message = f"Session updated: {fmt_dt(merged['starts_at'])}."
        if "capacity" in changed and changed["capacity"] > session.capacity:
            # Same transaction, so new places and their promotions land together.
            promoted = booking.promote_waitlist(conn, session.id, now)
            if promoted:
                message += f" {len(promoted)} waiting student(s) booked."
        return Result.success(message, {"session_id": session.id})


def delete_session(engine: Engine, actor_id: int, session_id: int,
                   now: datetime | None = None) -> Result:
    """Delete an instructor's own session that nobody ever booked or waited for.

    Rules: R2.8, R2.11, section 3 (MANAGE_OWN_SESSIONS).
    """
    now = now or utcnow()
    with engine.begin() as conn:
        session, refusal = _load_owned(conn, actor_id, session_id)
        if refusal:
            return refusal
        ever_booked, ever_waited = q.history_flags(conn, session.id)
        refusal = rules.check_delete(
            now=now, starts_at=session.starts_at, status=session.status,
            ever_booked=ever_booked, ever_waited=ever_waited,
        )
        if refusal:
            return refusal
        q.delete_session(conn, session.id)
        return Result.success(f"Session deleted: {fmt_dt(session.starts_at)}.")


def list_my_sessions(engine: Engine, actor_id: int, now: datetime | None = None) -> Result:
    """Return the acting instructor's sessions from now to the end of Lisbon today + 14, any status.

    Rules: R2.2, section 3 (MANAGE_OWN_SESSIONS), section 11 (My sessions).
    """
    now = now or utcnow()
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return _not_found()
        denied = require(actor, Action.MANAGE_OWN_SESSIONS, owner_id=actor.id)
        if denied:
            return denied
        # Local midnight after the last bookable day, so every start R2.2 allows is listed.
        end = from_local(local_date(now) + timedelta(days=MAX_DAYS_AHEAD + 1), time(0, 0))
        sessions = q.instructor_sessions(conn, actor.id, now, end)
        return Result.success(f"{len(sessions)} upcoming session(s).", sessions)


def call_off(engine: Engine, actor_id: int, session_id: int, category: str, reason: str,
             now: datetime | None = None) -> Result:
    """Call a session off for everyone, refunding and notifying them.

    Stub owned by Member 3: refuses until the Sessions lane builds it.

    Rules: R8.1-R8.5.
    """
    return Result.fail(Code.NOT_FOUND, "Call-off is not built yet")
