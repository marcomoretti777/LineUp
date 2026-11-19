"""Pure booking, waitlist and cancellation rules.

Each check returns None when the action is allowed, or a refused Result
whose code decides what the screen shows. Checks run in a fixed order so
the earliest broken rule always names the refusal.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from lineup.config import BOOKING_CUTOFF, REFUND_WINDOW
from lineup.models import BookingStatus, Code, Result, Role, SessionStatus, fill
from lineup.timeutil import fmt_time


def overlaps(a_start: datetime, a_min: int, b_start: datetime, b_min: int) -> bool:
    """Say whether two sessions share any minute, so back-to-back sessions do not clash.

    Rules: R3.5.
    """
    a_end = a_start + timedelta(minutes=a_min)
    b_end = b_start + timedelta(minutes=b_min)
    return a_start < b_end and b_start < a_end


def booking_open(now: datetime, starts_at: datetime) -> bool:
    """Say whether booking is still open, which it is up to and including the cutoff.

    Rules: R3.3.
    """
    return now <= starts_at - BOOKING_CUTOFF


def refund_due(now: datetime, starts_at: datetime) -> bool:
    """Say whether cancelling now earns a refund, which it does up to and including the window.

    Rules: R5.2.
    """
    return now <= starts_at - REFUND_WINDOW


def _closed_or_cutoff(
    session_status: SessionStatus, now: datetime, starts_at: datetime, what: str
) -> Result | None:
    # Shared by booking and waitlist so both close at exactly the same moment.
    if session_status == SessionStatus.CALLED_OFF:
        return Result.fail(
            Code.CLOSED,
            fill(Code.CLOSED, what="this called-off session", time=fmt_time(starts_at)),
        )
    if not booking_open(now, starts_at):
        cutoff = fmt_time(starts_at - BOOKING_CUTOFF)
        return Result.fail(Code.CLOSED, fill(Code.CLOSED, what=what, time=cutoff))
    return None


def _clash(starts_at: datetime, clash_at: datetime | None) -> Result:
    # The service may pass the clashing booking's start so the message names it (A4).
    return Result.fail(Code.CLASH, fill(Code.CLASH, time=fmt_time(clash_at or starts_at)))


def check_can_book(
    *,
    role: Role,
    session_status: SessionStatus,
    now: datetime,
    starts_at: datetime,
    already_booked: bool,
    has_clash: bool,
    balance: int,
    clash_at: datetime | None = None,
) -> Result | None:
    """Return the refusal for a student booking a session, or None when it is allowed.

    Rules: R3.1, R3.2, R3.3, R3.4, R3.5, R3.7.
    """
    if role != Role.STUDENT:
        return Result.fail(Code.FORBIDDEN, fill(Code.FORBIDDEN))
    closed = _closed_or_cutoff(session_status, now, starts_at, "booking")
    if closed:
        return closed
    if already_booked:
        return Result.fail(Code.DUPLICATE, fill(Code.DUPLICATE))
    if has_clash:
        return _clash(starts_at, clash_at)
    if balance < 1:
        return Result.fail(Code.NO_CREDITS, fill(Code.NO_CREDITS))
    return None


def check_can_join_waitlist(
    *,
    role: Role,
    session_status: SessionStatus,
    now: datetime,
    starts_at: datetime,
    is_full: bool,
    already_booked: bool,
    already_waiting: bool,
    has_clash: bool,
    clash_at: datetime | None = None,
) -> Result | None:
    """Return the refusal for a student joining a waitlist, or None when it is allowed.

    Rules: R4.1.
    """
    if role != Role.STUDENT:
        return Result.fail(Code.FORBIDDEN, fill(Code.FORBIDDEN))
    closed = _closed_or_cutoff(session_status, now, starts_at, "the waitlist")
    if closed:
        return closed
    # Duplicate before not_full: a booked student should hear they are booked,
    # not be told to book again.
    if already_booked or already_waiting:
        return Result.fail(Code.DUPLICATE, fill(Code.DUPLICATE))
    if not is_full:
        return Result.fail(Code.NOT_FULL, fill(Code.NOT_FULL))
    if has_clash:
        return _clash(starts_at, clash_at)
    return None


def check_can_cancel(
    *,
    is_owner: bool,
    booking_status: BookingStatus,
    now: datetime,
    starts_at: datetime,
) -> Result | None:
    """Return the refusal for a student cancelling a booking, or None when it is allowed.

    Rules: R5.1, R5.4.
    """
    if not is_owner:
        return Result.fail(Code.FORBIDDEN, fill(Code.FORBIDDEN))
    if booking_status != BookingStatus.CONFIRMED:
        return Result.fail(Code.ALREADY_DONE, fill(Code.ALREADY_DONE))
    if now >= starts_at:
        return Result.fail(
            Code.CLOSED, fill(Code.CLOSED, what="cancellation", time=fmt_time(starts_at))
        )
    return None


def promotion_order(entries: Iterable[Any]) -> list[Any]:
    """Return waitlist entries earliest joiner first, ties broken by id, without changing the input.

    Rules: R4.2.
    """
    return sorted(entries, key=lambda e: (e.joined_at, e.id))
