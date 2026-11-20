"""Service tests for the per-session status helper behind the sessions page (LU03-LU05)."""

from datetime import timedelta

import pytest
from conftest import add_waiting, give_credits, make_booking, make_member, make_session
from sqlalchemy import update

from lineup import schema


def _status(engine, actor_id, session_ids):
    # Imported here so a missing service fails each test, not collection.
    from lineup.services.booking import my_status_for_sessions

    return my_status_for_sessions(engine, actor_id, session_ids)


@pytest.fixture
def instructor(engine):
    return make_member(engine, role="instructor")


@pytest.fixture
def student(engine):
    return make_member(engine)


def _full_session(engine, instructor, start, holder=None):
    # A capacity-1 session filled by another student, so waiting entries are realistic.
    session_id = make_session(engine, instructor, start, capacity=1)
    holder = holder or make_member(engine)
    give_credits(engine, holder, 1)
    make_booking(engine, holder, session_id)
    return session_id


def test_booked_session_says_booked(engine, now, instructor, student):
    session_id = make_session(engine, instructor, now + timedelta(days=2))
    give_credits(engine, student, 1)
    make_booking(engine, student, session_id)

    assert _status(engine, student, [session_id]) == {session_id: "booked"}


def test_waiting_session_gives_position_by_join_time_not_id(engine, now, instructor, student):
    session_id = _full_session(engine, instructor, now + timedelta(days=2))
    add_waiting(engine, student, session_id, joined_at=now - timedelta(hours=1))
    # Inserted later (higher id) but joined earlier, so it is ahead of the student.
    add_waiting(engine, make_member(engine), session_id, joined_at=now - timedelta(hours=2))

    assert _status(engine, student, [session_id]) == {session_id: ("waiting", 2)}


def test_session_without_booking_or_entry_maps_to_none(engine, now, instructor, student):
    booked = make_session(engine, instructor, now + timedelta(days=2))
    free = make_session(engine, instructor, now + timedelta(days=3))
    give_credits(engine, student, 1)
    make_booking(engine, student, booked)

    assert _status(engine, student, [booked, free]) == {booked: "booked", free: None}


def test_mixed_sessions_each_get_their_own_status(engine, now, instructor, student):
    booked = make_session(engine, instructor, now + timedelta(days=1))
    waiting = _full_session(engine, instructor, now + timedelta(days=2))
    neither = make_session(engine, instructor, now + timedelta(days=3))
    give_credits(engine, student, 1)
    make_booking(engine, student, booked)
    add_waiting(engine, student, waiting, joined_at=now)

    assert _status(engine, student, [booked, waiting, neither]) == {
        booked: "booked",
        waiting: ("waiting", 1),
        neither: None,
    }


def test_other_students_bookings_and_entries_do_not_show(engine, now, instructor, student):
    other = make_member(engine)
    booked_by_other = _full_session(engine, instructor, now + timedelta(days=2), holder=other)
    other_waiting = _full_session(engine, instructor, now + timedelta(days=3))
    add_waiting(engine, other, other_waiting, joined_at=now)

    assert _status(engine, student, [booked_by_other, other_waiting]) == {
        booked_by_other: None,
        other_waiting: None,
    }


def test_cancelled_booking_maps_to_none(engine, now, instructor, student):
    session_id = make_session(engine, instructor, now + timedelta(days=2))
    give_credits(engine, student, 1)
    booking_id = make_booking(engine, student, session_id)
    with engine.begin() as conn:
        conn.execute(
            update(schema.bookings)
            .where(schema.bookings.c.id == booking_id)
            .values(status="cancelled", cancelled_at=now)
        )
        conn.execute(
            update(schema.surf_sessions)
            .where(schema.surf_sessions.c.id == session_id)
            .values(booked_count=0)
        )

    assert _status(engine, student, [session_id]) == {session_id: None}


@pytest.mark.parametrize("status", ["left", "removed", "cleared"])
def test_entry_no_longer_waiting_maps_to_none(engine, now, instructor, student, status):
    session_id = _full_session(engine, instructor, now + timedelta(days=2))
    entry_id = add_waiting(engine, student, session_id, joined_at=now)
    with engine.begin() as conn:
        conn.execute(
            update(schema.waitlist_entries)
            .where(schema.waitlist_entries.c.id == entry_id)
            .values(status=status)
        )

    assert _status(engine, student, [session_id]) == {session_id: None}


def test_entries_that_left_do_not_count_towards_position(engine, now, instructor, student):
    session_id = _full_session(engine, instructor, now + timedelta(days=2))
    gone = add_waiting(engine, make_member(engine), session_id, joined_at=now - timedelta(hours=2))
    add_waiting(engine, student, session_id, joined_at=now - timedelta(hours=1))
    with engine.begin() as conn:
        conn.execute(
            update(schema.waitlist_entries)
            .where(schema.waitlist_entries.c.id == gone)
            .values(status="left")
        )

    assert _status(engine, student, [session_id]) == {session_id: ("waiting", 1)}


@pytest.mark.parametrize("role", ["instructor", "admin"])
def test_staff_get_an_empty_mapping(engine, now, instructor, role):
    staff = make_member(engine, role=role)
    session_id = make_session(engine, instructor, now + timedelta(days=2))

    assert _status(engine, staff, [session_id]) == {}


def test_unknown_actor_gets_an_empty_mapping(engine, now, instructor):
    session_id = make_session(engine, instructor, now + timedelta(days=2))

    assert _status(engine, 999_999, [session_id]) == {}


def test_no_session_ids_gives_an_empty_mapping(engine, student):
    assert _status(engine, student, []) == {}


def _cards(engine, actor_id, now):
    from lineup.services.booking import session_cards

    return {card.session.id: card for card in session_cards(engine, actor_id, now=now)}


def test_cards_show_places_waiting_count_and_free_cancel_time(engine, now, instructor, student):
    start = now + timedelta(days=2)
    open_id = make_session(engine, instructor, start, capacity=6)
    give_credits(engine, student, 1)
    full_id = _full_session(engine, instructor, now + timedelta(days=3))
    for hours in (3, 2, 1):
        add_waiting(engine, make_member(engine), full_id, joined_at=now - timedelta(hours=hours))

    cards = _cards(engine, student, now)

    assert cards[open_id].session.capacity - cards[open_id].session.booked_count == 6
    assert cards[open_id].waiting_count == 0
    assert cards[open_id].free_cancel_until == start - timedelta(hours=24)
    assert cards[full_id].waiting_count == 3


def test_open_session_with_credit_is_bookable(engine, now, instructor, student):
    session_id = make_session(engine, instructor, now + timedelta(days=2))
    give_credits(engine, student, 1)

    card = _cards(engine, student, now)[session_id]

    assert (card.can_book, card.book_block, card.can_join, card.my_status) == (
        True, None, False, None
    )


def test_booked_session_is_blocked_as_already_booked(engine, now, instructor, student):
    session_id = make_session(engine, instructor, now + timedelta(days=2))
    give_credits(engine, student, 2)
    make_booking(engine, student, session_id)

    card = _cards(engine, student, now)[session_id]

    assert (card.can_book, card.book_block, card.my_status) == (False, "Already booked", "booked")


def test_waiting_session_is_blocked_as_already_waiting(engine, now, instructor, student):
    session_id = _full_session(engine, instructor, now + timedelta(days=2))
    add_waiting(engine, student, session_id, joined_at=now)

    card = _cards(engine, student, now)[session_id]

    assert (card.can_book, card.can_join, card.book_block, card.my_status) == (
        False, False, "Already waiting", ("waiting", 1)
    )


def test_session_inside_the_cutoff_says_booking_closed(engine, now, instructor, student):
    open_id = make_session(engine, instructor, now + timedelta(hours=1, minutes=59))
    full_id = _full_session(engine, instructor, now + timedelta(hours=1, minutes=30))
    give_credits(engine, student, 1)

    cards = _cards(engine, student, now)

    for session_id in (open_id, full_id):
        assert (cards[session_id].can_book, cards[session_id].can_join,
                cards[session_id].book_block) == (False, False, "Booking closed")


def test_clash_and_no_credits_leave_the_button_on_but_are_not_bookable(
    engine, now, instructor, student
):
    mine = make_session(engine, instructor, now + timedelta(days=1))
    clashing = make_session(engine, instructor, now + timedelta(days=1, minutes=30))
    give_credits(engine, student, 1)
    make_booking(engine, student, mine)
    # The one credit is spent, so the clashing session is also unaffordable.
    later = make_session(engine, instructor, now + timedelta(days=3))

    cards = _cards(engine, student, now)

    for session_id in (clashing, later):
        assert (cards[session_id].can_book, cards[session_id].book_block) == (False, None)


def test_full_session_offers_the_waitlist_not_booking(engine, now, instructor, student):
    session_id = _full_session(engine, instructor, now + timedelta(days=2))
    give_credits(engine, student, 1)

    card = _cards(engine, student, now)[session_id]

    assert (card.can_book, card.can_join, card.book_block) == (False, True, None)


@pytest.mark.parametrize("role", ["instructor", "admin"])
def test_staff_see_cards_without_actions(engine, now, instructor, role):
    staff = make_member(engine, role=role)
    session_id = make_session(engine, instructor, now + timedelta(days=2))

    card = _cards(engine, staff, now)[session_id]

    assert (card.can_book, card.can_join, card.book_block, card.my_status) == (
        False, False, None, None
    )


def test_cards_list_only_scheduled_sessions_in_the_next_14_days(engine, now, instructor, student):
    listed = make_session(engine, instructor, now + timedelta(days=2))
    make_session(engine, instructor, now + timedelta(days=3), status="called_off")
    make_session(engine, instructor, now + timedelta(days=20))
    make_session(engine, instructor, now - timedelta(hours=1))

    assert list(_cards(engine, student, now)) == [listed]


def test_no_sessions_gives_no_cards(engine, now, student):
    assert _cards(engine, student, now) == {}


@pytest.mark.parametrize(
    ("label", "warns"),
    [("go", False), ("marginal", False), ("no_go", True), ("unknown", True)],
)
def test_call_off_warning_only_for_no_go_and_unknown(label, warns):
    from lineup.models import Condition, Label
    from lineup.services.booking import call_off_warning

    warning = call_off_warning(Condition(Label(label), None, None, ""))

    if warns:
        assert warning == (
            "The instructor may call this session off; you would get your credit back."
        )
    else:
        assert warning is None
