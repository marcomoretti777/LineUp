"""The acceptance scenarios of spec section 6, end to end.

Each test drives one scenario through public service functions only, the
way a screen would, and asserts on Result codes rather than wording.

Part 1 covers the scenarios whose services are on main with a real body:
A2-A7, all served by lineup/services/booking.py. The rest arrive as their
lanes merge; the pull request lists each one and its blocker.
"""

from datetime import timedelta

from lineup import db
from lineup.models import Code
from lineup.services import booking
from tests.conftest import add_waiting, give_credits, make_member, make_session


def balance(engine, member_id):
    """The member's credit balance, read the way a screen reads it."""
    with engine.begin() as conn:
        return db.ledger_balance(conn, member_id)


def unread(engine, member_id):
    """How many notifications the member has not read yet."""
    with engine.begin() as conn:
        return db.unread_count(conn, member_id)


def booked_count(engine, session_id):
    """Places taken in a session, as stored."""
    with engine.begin() as conn:
        return db.get_session(conn, session_id).booked_count


def test_a2_booking_cutoff(engine, now):
    """A2: booking closes two hours before the start (R3.3)."""
    instructor = make_member(engine, role="instructor")
    ana = make_member(engine)
    bruno = make_member(engine)
    give_credits(engine, ana, 2)
    give_credits(engine, bruno, 2)

    start = now.replace(hour=10, minute=0)
    session = make_session(engine, instructor, start, capacity=4)

    booked = booking.book(engine, ana, session, now=start - timedelta(hours=2))
    assert booked.ok is True

    too_late = booking.book(engine, bruno, session,
                            now=start - timedelta(hours=1, minutes=59))
    assert too_late.ok is False
    assert too_late.code is Code.CLOSED

    assert booked_count(engine, session) == 1
    assert balance(engine, bruno) == 2


def test_a3_last_credit(engine, now):
    """A3: the last credit is spent once and never goes negative (R3.4, R10.7)."""
    instructor = make_member(engine, role="instructor")
    ana = make_member(engine)
    give_credits(engine, ana, 1)

    first = make_session(engine, instructor, now + timedelta(days=1))
    second = make_session(engine, instructor, now + timedelta(days=2))

    spent = booking.book(engine, ana, first, now=now)
    assert spent.ok is True
    assert balance(engine, ana) == 0

    refused = booking.book(engine, ana, second, now=now)
    assert refused.ok is False
    assert refused.code is Code.NO_CREDITS

    assert balance(engine, ana) == 0
    assert booked_count(engine, second) == 0


def test_a4_clash(engine, now):
    """A4: an overlapping session is refused; back to back is allowed (R3.5)."""
    instructor = make_member(engine, role="instructor")
    ana = make_member(engine)
    give_credits(engine, ana, 3)

    start = now + timedelta(days=1)
    booked = make_session(engine, instructor, start, duration_min=90)
    assert booking.book(engine, ana, booked, now=now).ok is True

    overlapping = make_session(engine, instructor, start + timedelta(hours=1),
                               duration_min=60)
    clash = booking.book(engine, ana, overlapping, now=now)
    assert clash.ok is False
    assert clash.code is Code.CLASH

    back_to_back = make_session(engine, instructor, start + timedelta(minutes=90),
                                duration_min=60)
    assert booking.book(engine, ana, back_to_back, now=now).ok is True

    assert balance(engine, ana) == 1
    assert booked_count(engine, overlapping) == 0


def test_a5_last_place(engine, now):
    """A5: the last place is taken once; the next student waits (R3.8, R4.1)."""
    instructor = make_member(engine, role="instructor")
    early = make_member(engine)
    ana = make_member(engine)
    bruno = make_member(engine)
    for student in (early, ana, bruno):
        give_credits(engine, student, 2)

    start = now + timedelta(days=1)
    session = make_session(engine, instructor, start, capacity=2)

    assert booking.book(engine, early, session, now=now).ok is True
    assert booking.book(engine, ana, session, now=now).ok is True
    assert booked_count(engine, session) == 2

    full = booking.book(engine, bruno, session, now=now)
    assert full.ok is False
    assert full.code is Code.FULL

    waiting = booking.join_waitlist(engine, bruno, session, now=now)
    assert waiting.ok is True
    assert booking.waitlist_position(engine, bruno, session) == 1

    # The waitlist never takes a place or a credit (R4.1).
    assert booked_count(engine, session) == 2
    assert balance(engine, bruno) == 2


def test_a6_promotion_with_a_skip(engine, now):
    """A6: a freed place skips a student with no credits (R4.3, R5.2)."""
    instructor = make_member(engine, role="instructor")
    ana = make_member(engine)
    carla = make_member(engine)
    bruno = make_member(engine)

    start = now + timedelta(hours=30)
    session = make_session(engine, instructor, start, capacity=2)

    other = make_member(engine)
    give_credits(engine, other, 1)
    give_credits(engine, ana, 1)
    assert booking.book(engine, other, session, now=now).ok is True
    booked = booking.book(engine, ana, session, now=now)
    assert booked.ok is True
    assert booked_count(engine, session) == 2

    # Carla waits first but cannot pay; Bruno waits second and can.
    add_waiting(engine, carla, session, now)
    add_waiting(engine, bruno, session, now + timedelta(minutes=1))
    give_credits(engine, bruno, 1)
    assert balance(engine, carla) == 0

    cancelled = booking.cancel_booking(engine, ana, booked.data["booking_id"], now=now)
    assert cancelled.ok is True
    assert cancelled.data["refunded"] is True
    assert balance(engine, ana) == 1

    # Bruno takes the place and pays for it; Carla is skipped, not charged.
    assert balance(engine, bruno) == 0
    assert balance(engine, carla) == 0
    assert booked_count(engine, session) == 2
    assert booking.waitlist_position(engine, bruno, session) is None

    # Everyone involved hears about it.
    assert unread(engine, ana) >= 1
    assert unread(engine, bruno) >= 1
    assert unread(engine, carla) >= 1


def test_a7_refund_window(engine, now):
    """A7: the 24-hour refund window, at and either side of its edge (R5.1, R5.2)."""
    instructor = make_member(engine, role="instructor")
    start = now + timedelta(days=3)
    session = make_session(engine, instructor, start, capacity=4)

    on_time = make_member(engine)
    late = make_member(engine)
    at_start = make_member(engine)
    bookings = {}
    for student in (on_time, late, at_start):
        give_credits(engine, student, 1)
        result = booking.book(engine, student, session, now=now)
        assert result.ok is True
        bookings[student] = result.data["booking_id"]

    # Exactly 24 hours before the start still earns the refund.
    edge = start - timedelta(hours=24)
    preview = booking.cancel_preview(engine, on_time, bookings[on_time], now=edge)
    assert preview.data["refund"] is True
    refunded = booking.cancel_booking(engine, on_time, bookings[on_time], now=edge)
    assert refunded.ok is True
    assert refunded.data["refunded"] is True
    assert balance(engine, on_time) == 1

    # One minute later it does not, and the preview says so without writing.
    just_late = start - timedelta(hours=23, minutes=59)
    warning = booking.cancel_preview(engine, late, bookings[late], now=just_late)
    assert warning.ok is True
    assert warning.data["refund"] is False
    assert balance(engine, late) == 0

    no_refund = booking.cancel_booking(engine, late, bookings[late], now=just_late)
    assert no_refund.ok is True
    assert no_refund.data["refunded"] is False
    assert balance(engine, late) == 0

    # Once it has started, cancelling is refused outright (R5.1).
    too_late = booking.cancel_booking(engine, at_start, bookings[at_start], now=start)
    assert too_late.ok is False
    assert too_late.code is Code.CLOSED
    assert booked_count(engine, session) == 1
