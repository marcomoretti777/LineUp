"""Session actions. Owner: Member 3 (Sessions and forecast lane).

Instructors create, edit, delete and list their own sessions here. Every
action follows the contract's service pattern: load the actor, check the
permission, ask the pure rule in lineup/logic/sessions.py, then write in
one transaction. call_off refunds, clears and notifies in that same
transaction; decision_needed feeds "Needs your decision" on My sessions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Connection, Engine

from lineup import db
from lineup.config import DURATIONS, MAX_DAYS_AHEAD
from lineup.logic import sessions as rules
from lineup.models import (
    MESSAGES,
    CallOffCategory,
    Code,
    Condition,
    Label,
    LedgerKind,
    Result,
    SessionStatus,
    SessionView,
    fill,
)
from lineup.permissions import Action, require
from lineup.queries import sessions as q

# Imported as modules so tests can replace promote_waitlist with a spy, and so
# decision_needed picks up whichever conditions_for_sessions is current.
from lineup.services import booking, forecast
from lineup.timeutil import fmt_dt, fmt_time, from_local, local_date, to_local, utcnow

_EDITABLE = ("day", "start_time", "duration_min", "capacity", "level")
REASON_MIN, REASON_MAX = 3, 200
DECISION_WINDOW = timedelta(hours=72)
_CATEGORY_LABELS = {
    CallOffCategory.CONDITIONS: "Conditions",
    CallOffCategory.INSTRUCTOR_UNAVAILABLE: "Instructor unavailable",
    CallOffCategory.OTHER: "Other",
}
_NEEDS_DECISION = (Label.NO_GO, Label.UNKNOWN)


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


def _check_call_off_input(category: str, reason: str) -> Result | None:
    # Kept here because this task may not change lineup/logic/sessions.py.
    if category not in {c.value for c in CallOffCategory}:
        return Result.fail(Code.INVALID, fill(
            Code.INVALID, field="Category", problem=f"{category!r} is not a call-off category",
            allowed=", ".join(_CATEGORY_LABELS.values()),
        ))
    length = len(reason)
    if not REASON_MIN <= length <= REASON_MAX:
        return Result.fail(Code.INVALID, fill(
            Code.INVALID, field="Reason", problem=f"it has {length} characters",
            allowed=f"{REASON_MIN} to {REASON_MAX} characters",
        ))
    return None


def call_off(engine: Engine, actor_id: int, session_id: int, category: str, reason: str,
             now: datetime | None = None) -> Result:
    """Call a session off for everyone: refund every booking once, clear the waitlist, notify all.

    Rules: R8.1, R8.2, R8.3, R8.4, R8.5, R10.8, R11.1, R11.2.
    """
    now = now or utcnow()
    reason = (reason or "").strip()
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return _not_found()
        session = db.get_session(conn, session_id)
        if session is None:
            # Check the role first, so a student never learns which ids exist.
            return require(actor, Action.CALL_OFF, owner_id=actor.id) or _not_found()
        denied = require(actor, Action.CALL_OFF, owner_id=session.instructor_id)
        if denied:
            return denied
        # Before the clock check, so a repeat always reads as "already done".
        if session.status == SessionStatus.CALLED_OFF:
            return Result.fail(Code.ALREADY_DONE, fill(Code.ALREADY_DONE))
        if now >= session.ends_at:
            return Result.fail(Code.CLOSED, fill(
                Code.CLOSED, what="calling off", time=fmt_time(session.ends_at),
            ))
        refusal = _check_call_off_input(category, reason)
        if refusal:
            return refusal

        # The status read above may be stale; only this guarded UPDATE decides.
        if not q.mark_called_off(conn, session.id, category, reason, now):
            return Result.fail(Code.ALREADY_DONE, fill(Code.ALREADY_DONE))
        booked = q.confirmed_bookings(conn, session.id)
        waiting = q.waiting_members(conn, session.id)
        q.call_off_bookings(conn, session.id, now)
        q.clear_waitlist(conn, session.id, now)

        when = fmt_dt(session.starts_at)
        why = f"{_CATEGORY_LABELS[CallOffCategory(category)]}: {reason}"
        refunded = 0
        for booking_id, member_id in booked:
            # The unique ref is the guard against a second refund for the same booking.
            if db.ledger_add(conn, member_id, 1, LedgerKind.REFUND, f"refund:{booking_id}",
                             note="session called off"):
                q.mark_refunded(conn, booking_id)
                refunded += 1
            db.notify(conn, member_id, "called_off",
                      f"Called off: {when} ({why}). 1 credit refunded.")
        for _, member_id in waiting:
            db.notify(conn, member_id, "called_off",
                      f"Called off: {when} ({why}). You are no longer on its waitlist.")

        return Result.success(
            f"Called off: {when}. {refunded} credit(s) refunded, "
            f"{len(waiting)} waiting student(s) notified.",
            {"refunded": refunded, "cleared": len(waiting)},
        )


ConditionsFn = Callable[..., Mapping[int, Condition]]


def decision_needed(engine: Engine, actor_id: int, now: datetime | None = None,
                    conditions: ConditionsFn | None = None) -> Result:
    """Return the actor's own scheduled sessions in the next 72 h labelled No-go or Unknown.

    Result.data is a list of (SessionView, Condition), earliest first.

    Rules: R6.5, R8, section 11 (My sessions, "Needs your decision").
    """
    now = now or utcnow()
    conditions = conditions or forecast.conditions_for_sessions
    with engine.connect() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return _not_found()
        denied = require(actor, Action.MANAGE_OWN_SESSIONS, owner_id=actor.id)
        if denied:
            return denied
        sessions: list[SessionView] = [
            s for s in q.instructor_sessions(conn, actor.id, now, now + DECISION_WINDOW)
            if s.status == SessionStatus.SCHEDULED and s.starts_at > now
        ]
    # Outside the read: the forecast service may open its own transaction to refresh.
    labels = conditions(engine, sessions, now=now)
    # A session the forecast left out has no label, which is Unknown (R6.5).
    unknown = Condition(Label.UNKNOWN, None, None, "No forecast for this session")
    flagged = [
        (s, labels.get(s.id, unknown)) for s in sessions
        if labels.get(s.id, unknown).label in _NEEDS_DECISION
    ]
    return Result.success(f"{len(flagged)} session(s) need your decision.", flagged)
