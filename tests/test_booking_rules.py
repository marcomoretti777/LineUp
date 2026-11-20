"""Pure booking, waitlist and cancellation rules (R3, R4.1-R4.2, R5)."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from lineup.logic.booking import (
    booking_open,
    check_can_book,
    check_can_cancel,
    check_can_join_waitlist,
    overlaps,
    promotion_order,
    refund_due,
)
from lineup.models import MESSAGES, BookingStatus, Code, Role, SessionStatus


# Local until tests/conftest.py (F03) provides the shared `now` fixture.
@pytest.fixture
def now():
    return datetime(2026, 11, 20, 9, 0)


def _book_kwargs(now, **overrides):
    # Baseline is a booking every rule allows, so each test flips exactly one input.
    kwargs = dict(
        role=Role.STUDENT,
        session_status=SessionStatus.SCHEDULED,
        now=now,
        starts_at=now + timedelta(hours=3),
        already_booked=False,
        has_clash=False,
        balance=1,
    )
    kwargs.update(overrides)
    return kwargs


def _wait_kwargs(now, **overrides):
    kwargs = dict(
        role=Role.STUDENT,
        session_status=SessionStatus.SCHEDULED,
        now=now,
        starts_at=now + timedelta(hours=3),
        is_full=True,
        already_booked=False,
        already_waiting=False,
        has_clash=False,
    )
    kwargs.update(overrides)
    return kwargs


def _cancel_kwargs(now, **overrides):
    kwargs = dict(
        is_owner=True,
        booking_status=BookingStatus.CONFIRMED,
        now=now,
        starts_at=now + timedelta(hours=3),
    )
    kwargs.update(overrides)
    return kwargs


def _at(hour, minute=0):
    return datetime(2026, 11, 21, hour, minute)


def _assert_refused(result, code):
    assert result is not None
    assert result.ok is False
    assert result.code == code


# --- overlaps (R3.5) ---


def test_r3_5_overlap_partial_is_clash():
    assert overlaps(_at(10), 90, _at(11), 60) is True


def test_r3_5_back_to_back_is_not_clash():
    assert overlaps(_at(10), 90, _at(11, 30), 60) is False


def test_r3_5_session_before_is_not_clash():
    assert overlaps(_at(10), 90, _at(9), 60) is False


def test_r3_5_session_inside_another_is_clash():
    assert overlaps(_at(10), 120, _at(10, 30), 30) is True
    assert overlaps(_at(10, 30), 30, _at(10), 120) is True


# --- booking_open (R3.3) ---


def test_r3_3_booking_open_at_exactly_two_hours_before_start(now):
    assert booking_open(now, now + timedelta(hours=2)) is True


def test_r3_3_booking_closes_two_hours_before_start(now):
    assert booking_open(now, now + timedelta(hours=1, minutes=59)) is False


# --- refund_due (R5.2) ---


def test_r5_2_refund_at_exactly_24_hours_before_start(now):
    assert refund_due(now, now + timedelta(hours=24)) is True


def test_r5_2_no_refund_at_23_59_before_start(now):
    assert refund_due(now, now + timedelta(hours=23, minutes=59)) is False


# --- check_can_book (R3.1-R3.5, R3.7) ---


@pytest.mark.parametrize("role", [Role.INSTRUCTOR, Role.ADMIN])
def test_r3_1_instructor_and_admin_cannot_book(now, role):
    _assert_refused(check_can_book(**_book_kwargs(now, role=role)), Code.FORBIDDEN)


def test_r3_2_called_off_session_is_closed(now):
    result = check_can_book(**_book_kwargs(now, session_status=SessionStatus.CALLED_OFF))
    _assert_refused(result, Code.CLOSED)


def test_r3_3_book_after_cutoff_is_closed(now):
    starts_at = now + timedelta(hours=1, minutes=59)
    _assert_refused(check_can_book(**_book_kwargs(now, starts_at=starts_at)), Code.CLOSED)


def test_r3_3_book_at_cutoff_is_allowed(now):
    assert check_can_book(**_book_kwargs(now, starts_at=now + timedelta(hours=2))) is None


def test_r3_7_second_booking_is_duplicate(now):
    _assert_refused(check_can_book(**_book_kwargs(now, already_booked=True)), Code.DUPLICATE)


def test_r3_5_book_with_clash_is_clash(now):
    _assert_refused(check_can_book(**_book_kwargs(now, has_clash=True)), Code.CLASH)


def test_r3_4_zero_balance_is_no_credits(now):
    _assert_refused(check_can_book(**_book_kwargs(now, balance=0)), Code.NO_CREDITS)


def test_r3_4_balance_one_is_allowed(now):
    assert check_can_book(**_book_kwargs(now, balance=1)) is None


_ORDERED_BOOKING_FAULTS = [
    ("role", Role.INSTRUCTOR, Code.FORBIDDEN),
    ("session_status", SessionStatus.CALLED_OFF, Code.CLOSED),
    ("starts_at", "after_cutoff", Code.CLOSED),
    ("already_booked", True, Code.DUPLICATE),
    ("has_clash", True, Code.CLASH),
    ("balance", 0, Code.NO_CREDITS),
]


@pytest.mark.parametrize("index", range(len(_ORDERED_BOOKING_FAULTS)))
def test_r3_check_order_for_booking(now, index):
    # Break this check and every later one: the earliest check must decide the code.
    overrides = {}
    for field, value, _ in _ORDERED_BOOKING_FAULTS[index:]:
        if value == "after_cutoff":
            value = now + timedelta(hours=1, minutes=59)
        overrides[field] = value
    expected = _ORDERED_BOOKING_FAULTS[index][2]
    _assert_refused(check_can_book(**_book_kwargs(now, **overrides)), expected)


# --- check_can_join_waitlist (R4.1) ---


def test_r4_1_not_full_is_not_full(now):
    result = check_can_join_waitlist(**_wait_kwargs(now, is_full=False))
    _assert_refused(result, Code.NOT_FULL)


def test_r4_1_already_booked_is_duplicate(now):
    result = check_can_join_waitlist(**_wait_kwargs(now, already_booked=True))
    _assert_refused(result, Code.DUPLICATE)


def test_r4_1_already_waiting_is_duplicate(now):
    result = check_can_join_waitlist(**_wait_kwargs(now, already_waiting=True))
    _assert_refused(result, Code.DUPLICATE)


def test_r4_1_join_after_cutoff_is_closed(now):
    starts_at = now + timedelta(hours=1, minutes=59)
    result = check_can_join_waitlist(**_wait_kwargs(now, starts_at=starts_at))
    _assert_refused(result, Code.CLOSED)


def test_r4_1_called_off_is_closed(now):
    result = check_can_join_waitlist(
        **_wait_kwargs(now, session_status=SessionStatus.CALLED_OFF)
    )
    _assert_refused(result, Code.CLOSED)


def test_r4_1_join_with_clash_is_clash(now):
    result = check_can_join_waitlist(**_wait_kwargs(now, has_clash=True))
    _assert_refused(result, Code.CLASH)


@pytest.mark.parametrize("role", [Role.INSTRUCTOR, Role.ADMIN])
def test_r4_1_non_student_cannot_join(now, role):
    result = check_can_join_waitlist(**_wait_kwargs(now, role=role))
    _assert_refused(result, Code.FORBIDDEN)


def test_r4_1_student_with_zero_credits_may_join(now):
    # The waitlist check takes no balance at all: credit is only needed at promotion (R4.3).
    assert check_can_join_waitlist(**_wait_kwargs(now)) is None


# --- check_can_cancel (R5.1, R5.4) ---


def test_r5_1_cancel_other_students_booking_is_forbidden(now):
    result = check_can_cancel(**_cancel_kwargs(now, is_owner=False))
    _assert_refused(result, Code.FORBIDDEN)


@pytest.mark.parametrize("status", [BookingStatus.CANCELLED, BookingStatus.CALLED_OFF])
def test_r5_4_cancel_twice_is_already_done(now, status):
    result = check_can_cancel(**_cancel_kwargs(now, booking_status=status))
    _assert_refused(result, Code.ALREADY_DONE)


def test_r5_1_cancel_at_start_is_closed(now):
    result = check_can_cancel(**_cancel_kwargs(now, starts_at=now))
    _assert_refused(result, Code.CLOSED)


def test_r5_1_cancel_before_start_is_allowed(now):
    assert check_can_cancel(**_cancel_kwargs(now, starts_at=now + timedelta(minutes=1))) is None


def test_r5_4_already_done_wins_over_started(now):
    result = check_can_cancel(
        **_cancel_kwargs(now, booking_status=BookingStatus.CANCELLED, starts_at=now)
    )
    _assert_refused(result, Code.ALREADY_DONE)


# --- promotion_order (R4.2) ---


def test_r4_2_earliest_joiner_first(now):
    entries = [
        SimpleNamespace(id=1, joined_at=now + timedelta(minutes=5)),
        SimpleNamespace(id=2, joined_at=now),
        SimpleNamespace(id=3, joined_at=now + timedelta(minutes=1)),
    ]
    original = list(entries)
    assert [e.id for e in promotion_order(entries)] == [2, 3, 1]
    assert entries == original


def test_r4_2_tie_on_joined_at_breaks_by_id(now):
    entries = [
        SimpleNamespace(id=7, joined_at=now),
        SimpleNamespace(id=4, joined_at=now),
    ]
    assert [e.id for e in promotion_order(entries)] == [4, 7]


# --- Refusal messages ---


_REFUSALS = [
    ("book_forbidden", check_can_book, _book_kwargs, {"role": Role.ADMIN}, Code.FORBIDDEN),
    ("book_called_off", check_can_book, _book_kwargs,
     {"session_status": SessionStatus.CALLED_OFF}, Code.CLOSED),
    ("book_cutoff", check_can_book, _book_kwargs, {"starts_at": "after_cutoff"}, Code.CLOSED),
    ("book_duplicate", check_can_book, _book_kwargs, {"already_booked": True}, Code.DUPLICATE),
    ("book_clash", check_can_book, _book_kwargs, {"has_clash": True}, Code.CLASH),
    ("book_no_credits", check_can_book, _book_kwargs, {"balance": 0}, Code.NO_CREDITS),
    ("wait_forbidden", check_can_join_waitlist, _wait_kwargs,
     {"role": Role.INSTRUCTOR}, Code.FORBIDDEN),
    ("wait_not_full", check_can_join_waitlist, _wait_kwargs, {"is_full": False}, Code.NOT_FULL),
    ("wait_duplicate", check_can_join_waitlist, _wait_kwargs,
     {"already_waiting": True}, Code.DUPLICATE),
    ("wait_cutoff", check_can_join_waitlist, _wait_kwargs,
     {"starts_at": "after_cutoff"}, Code.CLOSED),
    ("wait_clash", check_can_join_waitlist, _wait_kwargs, {"has_clash": True}, Code.CLASH),
    ("cancel_forbidden", check_can_cancel, _cancel_kwargs, {"is_owner": False}, Code.FORBIDDEN),
    ("cancel_twice", check_can_cancel, _cancel_kwargs,
     {"booking_status": BookingStatus.CANCELLED}, Code.ALREADY_DONE),
    ("cancel_started", check_can_cancel, _cancel_kwargs, {"starts_at": "at_start"}, Code.CLOSED),
]


def _resolve(now, overrides):
    resolved = dict(overrides)
    if resolved.get("starts_at") == "after_cutoff":
        resolved["starts_at"] = now + timedelta(hours=1, minutes=59)
    elif resolved.get("starts_at") == "at_start":
        resolved["starts_at"] = now
    return resolved


@pytest.mark.parametrize(
    "check, make_kwargs, overrides, code",
    [r[1:] for r in _REFUSALS],
    ids=[r[0] for r in _REFUSALS],
)
def test_refusal_messages_come_from_catalogue(now, check, make_kwargs, overrides, code):
    # Compare against the template's fixed opening so the test doesn't duplicate the wording.
    result = check(**make_kwargs(now, **_resolve(now, overrides)))
    _assert_refused(result, code)
    assert result.message.startswith(MESSAGES[code].split("{")[0])
    assert "{" not in result.message


def test_r3_3_closed_message_names_booking_cutoff_time(now):
    starts_at = datetime(2026, 11, 20, 10, 30)
    result = check_can_book(**_book_kwargs(now, starts_at=starts_at))
    _assert_refused(result, Code.CLOSED)
    assert "08:30" in result.message


def test_r4_1_closed_message_names_waitlist_cutoff_time(now):
    starts_at = datetime(2026, 11, 20, 10, 30)
    result = check_can_join_waitlist(**_wait_kwargs(now, starts_at=starts_at))
    _assert_refused(result, Code.CLOSED)
    assert "08:30" in result.message


def test_r5_1_closed_message_names_session_start_time(now):
    starts_at = datetime(2026, 11, 20, 8, 45)
    result = check_can_cancel(**_cancel_kwargs(now, starts_at=starts_at))
    _assert_refused(result, Code.CLOSED)
    assert "08:45" in result.message
