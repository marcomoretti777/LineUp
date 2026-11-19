"""Booking, waitlist and cancellation actions. Owner: Member 2 (Booking lane)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, Engine

from lineup import db
from lineup.config import REFUND_WINDOW
from lineup.logic import booking as rules
from lineup.models import (
    BookingStatus,
    Code,
    LedgerKind,
    Result,
    SessionStatus,
    SessionView,
    WaitStatus,
    fill,
)
from lineup.permissions import Action, require
from lineup.queries import booking as q
from lineup.timeutil import fmt_dt, fmt_time, utcnow


# Short reasons stored on removed entries; other refusals store their code.
_REMOVAL_REASONS = {Code.NO_CREDITS: "no credits", Code.CLASH: "clash"}


def _clash_at(conn: Connection, member_id: int, session: SessionView) -> datetime | None:
    # Shared by book, join and promote so all three agree on what clashes; the
    # start is returned so the clash message can name it (A4).
    return next(
        (
            other.starts_at
            for other in q.confirmed_bookings_for_member(conn, member_id)
            if other.session_id != session.id
            and rules.overlaps(other.starts_at, other.duration_min,
                               session.starts_at, session.duration_min)
        ),
        None,
    )


def _position(conn: Connection, member_id: int, session_id: int) -> int | None:
    ordered = rules.promotion_order(q.waiting_entries(conn, session_id))
    return next(
        (i for i, entry in enumerate(ordered, start=1) if entry.member_id == member_id),
        None,
    )


def promote_waitlist(conn: Connection, session_id: int, now: datetime) -> list[int]:
    """Offer freed places to waiting students in join order and return the promoted ids.

    Rules: R4.2, R4.3, R4.4, R2.10, R5.3, R11.1.
    """
    session = db.get_session(conn, session_id)
    if (session is None or session.status != SessionStatus.SCHEDULED
            or not rules.booking_open(now, session.starts_at)):
        return []

    promoted: list[int] = []
    free = session.capacity - session.booked_count
    for entry in rules.promotion_order(q.waiting_entries(conn, session.id)):
        if free <= 0:
            break
        member = db.get_actor(conn, entry.member_id)
        if member is None:
            q.set_wait_status(conn, entry.id, WaitStatus.REMOVED, Code.NOT_FOUND.value, now)
            continue

        # Same lock as book(), so a promotion and a booking in another tab cannot
        # both spend this member's last credit.
        db.lock_member(conn, member.id)
        balance = db.ledger_balance(conn, member.id)
        clash_at = _clash_at(conn, member.id, session)
        refused = rules.check_can_book(
            role=member.role,
            session_status=session.status,
            now=now,
            starts_at=session.starts_at,
            already_booked=q.has_confirmed_booking(conn, member.id, session.id),
            has_clash=clash_at is not None,
            balance=balance,
            clash_at=clash_at,
        )
        if refused:
            reason = _REMOVAL_REASONS.get(refused.code, str(refused.code))
            q.set_wait_status(conn, entry.id, WaitStatus.REMOVED, reason, now)
            db.notify(
                conn, member.id, "waitlist_removed",
                f"Removed from the waitlist for {fmt_dt(session.starts_at)}. "
                f"{refused.message}",
            )
            continue

        # The free count read above may be stale; only this UPDATE decides.
        if not q.reserve_place(conn, session.id):
            break
        booking_id = q.insert_booking(conn, session.id, member.id, now)
        db.ledger_add(conn, member.id, -1, LedgerKind.BOOKING, f"booking:{booking_id}")
        q.set_wait_status(conn, entry.id, WaitStatus.PROMOTED, "promoted from waitlist", now)
        left = balance - 1
        db.notify(
            conn, member.id, "promoted",
            f"You got a place: {fmt_dt(session.starts_at)}. "
            f"{left} credit{'' if left == 1 else 's'} left. "
            f"Free cancellation until {fmt_dt(session.starts_at - REFUND_WINDOW)}.",
        )
        promoted.append(member.id)
        free -= 1
    return promoted


def join_waitlist(engine: Engine, actor_id: int, session_id: int,
                  now: datetime | None = None) -> Result:
    """Put a student on a full session's waitlist, without needing a credit.

    Rules: R4.1, R4.2, R4.6.
    """
    now = now or utcnow()
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
        denied = require(actor, Action.JOIN_WAITLIST, owner_id=actor.id)
        if denied:
            return denied
        session = db.get_session(conn, session_id)
        if session is None:
            return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))

        clash_at = _clash_at(conn, actor.id, session)
        refused = rules.check_can_join_waitlist(
            role=actor.role,
            session_status=session.status,
            now=now,
            starts_at=session.starts_at,
            is_full=session.booked_count >= session.capacity,
            already_booked=q.has_confirmed_booking(conn, actor.id, session.id),
            already_waiting=q.waiting_entry(conn, actor.id, session.id) is not None,
            has_clash=clash_at is not None,
            clash_at=clash_at,
        )
        if refused:
            return refused

        entry_id = q.insert_waiting_entry(conn, session.id, actor.id, now)
        position = _position(conn, actor.id, session.id)
        message = f"You're on the waitlist for {fmt_dt(session.starts_at)}: #{position}."
        return Result.success(message, {"entry_id": entry_id, "position": position})


def leave_waitlist(engine: Engine, actor_id: int, entry_id: int,
                   now: datetime | None = None) -> Result:
    """Take a student's own waiting entry off the waitlist, any time before the start.

    Rules: R4.5.
    """
    now = now or utcnow()
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
        entry = q.get_wait_entry(conn, entry_id)
        if entry is None:
            return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
        denied = require(actor, Action.LEAVE_WAITLIST, owner_id=entry.member_id)
        if denied:
            return denied
        if entry.status != WaitStatus.WAITING:
            return Result.fail(Code.ALREADY_DONE, fill(Code.ALREADY_DONE))
        if now >= entry.starts_at:
            return Result.fail(
                Code.CLOSED,
                fill(Code.CLOSED, what="the waitlist", time=fmt_time(entry.starts_at)),
            )
        # The status read above may be stale; only this guarded UPDATE decides.
        if not q.leave_entry(conn, entry.id, now):
            return Result.fail(Code.ALREADY_DONE, fill(Code.ALREADY_DONE))
        return Result.success(f"You left the waitlist for {fmt_dt(entry.starts_at)}.")


def waitlist_position(engine: Engine, actor_id: int, session_id: int) -> int | None:
    """Return a student's 1-based place in a session's waitlist, or None if not waiting.

    Rules: R4.2, R4.6.
    """
    with engine.connect() as conn:
        return _position(conn, actor_id, session_id)


def book(engine: Engine, actor_id: int, session_id: int, now: datetime | None = None) -> Result:
    """Book a place in a session for a student, charging 1 credit, in one transaction.

    Rules: R3.1, R3.2, R3.3, R3.4, R3.5, R3.7, R3.8, R3.9, R10.7, R10.8, R11.1.
    """
    now = now or utcnow()
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
        denied = require(actor, Action.BOOK, owner_id=actor.id)
        if denied:
            return denied
        session = db.get_session(conn, session_id)
        if session is None:
            return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))

        # Lock before reading the balance, so two tabs cannot both spend the last credit.
        db.lock_member(conn, actor.id)
        balance = db.ledger_balance(conn, actor.id)
        clash_at = _clash_at(conn, actor.id, session)
        refused = rules.check_can_book(
            role=actor.role,
            session_status=session.status,
            now=now,
            starts_at=session.starts_at,
            already_booked=q.has_confirmed_booking(conn, actor.id, session.id),
            has_clash=clash_at is not None,
            balance=balance,
            clash_at=clash_at,
        )
        if refused:
            return refused

        # The count read above may be stale; only this UPDATE decides who gets the place.
        if not q.reserve_place(conn, session.id):
            return Result.fail(Code.FULL, fill(Code.FULL), data={"can_join_waitlist": True})

        booking_id = q.insert_booking(conn, session.id, actor.id, now)
        db.ledger_add(conn, actor.id, -1, LedgerKind.BOOKING, f"booking:{booking_id}")
        entry_id = q.waiting_entry(conn, actor.id, session.id)
        if entry_id is not None:
            q.set_wait_status(conn, entry_id, WaitStatus.PROMOTED, "booked directly", now)

        left = balance - 1
        free_cancel_until = session.starts_at - REFUND_WINDOW
        message = (
            f"Booked: {fmt_dt(session.starts_at)}. "
            f"{left} credit{'' if left == 1 else 's'} left. "
            f"Free cancellation until {fmt_dt(free_cancel_until)}."
        )
        db.notify(conn, actor.id, "booking", message)
        return Result.success(
            message, {"booking_id": booking_id, "free_cancel_until": free_cancel_until}
        )


def _check_cancel(conn: Connection, actor_id: int, booking_id: int, now: datetime):
    # Shared by preview and cancel so the dialog never offers what cancel would refuse.
    actor = db.get_actor(conn, actor_id)
    if actor is None:
        return None, Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
    booking = q.get_booking(conn, booking_id)
    if booking is None:
        return None, Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
    denied = require(actor, Action.CANCEL_BOOKING, owner_id=booking.member_id)
    if denied:
        return None, denied
    refused = rules.check_can_cancel(
        is_owner=True,
        booking_status=BookingStatus(booking.status),
        now=now,
        starts_at=booking.starts_at,
    )
    if refused:
        return None, refused
    return booking, None


def cancel_preview(engine: Engine, actor_id: int, booking_id: int,
                   now: datetime | None = None) -> Result:
    """Say, without changing anything, whether cancelling a booking now earns a refund.

    Rules: R5.1, R5.2.
    """
    now = now or utcnow()
    with engine.connect() as conn:
        booking, refused = _check_cancel(conn, actor_id, booking_id, now)
        if refused:
            return refused
        deadline = booking.starts_at - REFUND_WINDOW
        refund = rules.refund_due(now, booking.starts_at)
        if refund:
            message = "Cancel now and you get 1 credit back."
        else:
            message = f"No refund: free cancellation ended {fmt_dt(deadline)}."
        return Result.success(message, {"refund": refund, "refund_deadline": deadline})


def cancel_booking(engine: Engine, actor_id: int, booking_id: int,
                   now: datetime | None = None) -> Result:
    """Cancel a student's booking, refund 1 credit inside the window and free the place.

    Rules: R5.1, R5.2, R5.3, R5.4, R10.8.
    """
    now = now or utcnow()
    with engine.begin() as conn:
        booking, refused = _check_cancel(conn, actor_id, booking_id, now)
        if refused:
            return refused

        db.lock_member(conn, booking.member_id)
        # The status read above may be stale; only this guarded UPDATE decides.
        if not q.set_booking_cancelled(conn, booking.id, now):
            return Result.fail(Code.ALREADY_DONE, fill(Code.ALREADY_DONE))
        q.release_place(conn, booking.session_id)

        refunded = False
        if rules.refund_due(now, booking.starts_at):
            # The unique ref is the guard against a second refund for the same booking.
            refunded = db.ledger_add(conn, booking.member_id, 1, LedgerKind.REFUND,
                                     f"refund:{booking.id}")
            if refunded:
                q.mark_refunded(conn, booking.id)

        promote_waitlist(conn, booking.session_id, now)

        outcome = (
            "1 credit refunded."
            if refunded
            else "No refund: cancelled less than 24 h before the start."
        )
        message = f"Cancelled: {fmt_dt(booking.starts_at)}. {outcome}"
        db.notify(conn, booking.member_id, "cancellation", message)
        return Result.success(message, {"refunded": refunded})
