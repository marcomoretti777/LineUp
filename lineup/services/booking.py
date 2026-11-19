"""Booking actions. Owner: Member 2 (Booking lane).

The lead created this stub in F03 so other lanes can call the contract
function now; Member 2 replaces the body in their own task.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, Engine

from lineup import db
from lineup.config import REFUND_WINDOW
from lineup.logic import booking as rules
from lineup.models import Code, LedgerKind, Result, WaitStatus, fill
from lineup.permissions import Action, require
from lineup.queries import booking as q
from lineup.timeutil import fmt_dt, utcnow


def promote_waitlist(conn: Connection, session_id: int, now: datetime) -> list[int]:
    """Offer freed places to waiting students in join order; return promoted ids.

    Stub owned by Member 2: promotes nobody until the Booking lane builds it.

    Rules: R4.3, R4.4, R2.10, R5.3.
    """
    return []


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
        clash_at = next(
            (
                other.starts_at
                for other in q.confirmed_bookings_for_member(conn, actor.id)
                if other.session_id != session.id
                and rules.overlaps(other.starts_at, other.duration_min,
                                   session.starts_at, session.duration_min)
            ),
            None,
        )
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
