"""Service tests for booking a session (R3.1-R3.9, R10.7, R10.8, R11.1)."""

from datetime import timedelta

from conftest import add_waiting, give_credits, make_booking, make_member, make_session
from sqlalchemy import func, select

from lineup import db, schema
from lineup.models import Code


def _book(engine, actor_id, session_id, now):
    # Imported here so a missing service fails each test, not collection.
    from lineup.services.booking import book

    return book(engine, actor_id, session_id, now=now)


def _count(engine, table, **where):
    with engine.connect() as conn:
        query = select(func.count()).select_from(table)
        for column, value in where.items():
            query = query.where(table.c[column] == value)
        return conn.execute(query).scalar_one()


def _written(engine):
    # Row counts of every table a booking writes, to prove a refusal wrote nothing.
    return {
        t.name: _count(engine, t)
        for t in (schema.bookings, schema.credit_ledger, schema.notifications,
                  schema.waitlist_entries)
    } | {"booked": _count_booked(engine)}


def _count_booked(engine):
    with engine.connect() as conn:
        return conn.execute(
            select(func.coalesce(func.sum(schema.surf_sessions.c.booked_count), 0))
        ).scalar_one()


def _booked_count(engine, session_id):
    s = schema.surf_sessions
    with engine.connect() as conn:
        return conn.execute(select(s.c.booked_count).where(s.c.id == session_id)).scalar_one()


def _balance(engine, member_id):
    with engine.connect() as conn:
        return db.ledger_balance(conn, member_id)


def _setup(engine, now, start=None, credits=1, **session_kwargs):
    instructor = make_member(engine, role="instructor")
    student = make_member(engine)
    if credits:
        give_credits(engine, student, credits)
    start = start or now + timedelta(days=1)
    session = make_session(engine, instructor, start, **session_kwargs)
    return instructor, student, session, start


def test_r3_4_student_with_one_credit_books_and_is_charged_once(engine, now):
    _, student, session, start = _setup(engine, now)

    result = _book(engine, student, session, now)

    assert result.ok, result.message
    booking_id = result.data["booking_id"]
    assert result.data["free_cancel_until"] == start - timedelta(hours=24)
    assert _balance(engine, student) == 0
    assert _booked_count(engine, session) == 1
    ledger = schema.credit_ledger
    with engine.connect() as conn:
        rows = conn.execute(
            select(ledger.c.delta, ledger.c.kind)
            .where(ledger.c.ref == f"booking:{booking_id}")
        ).all()
    assert [(r.delta, r.kind) for r in rows] == [(-1, "booking")]
    assert _count(engine, schema.notifications, member_id=student) == 1
    assert _count(engine, schema.notifications, member_id=student, kind="booking") == 1


def test_r3_1_instructor_cannot_book(engine, now):
    instructor, _, session, _ = _setup(engine, now)
    give_credits(engine, instructor, 1)
    before = _written(engine)

    result = _book(engine, instructor, session, now)

    assert result.code == Code.FORBIDDEN
    assert _written(engine) == before


def test_r3_2_called_off_session_is_closed(engine, now):
    _, student, session, _ = _setup(engine, now, status="called_off")
    before = _written(engine)

    result = _book(engine, student, session, now)

    assert result.code == Code.CLOSED
    assert _written(engine) == before


def test_r3_3_booking_open_at_exactly_two_hours_before_start(engine, now):
    _, student, session, _ = _setup(engine, now, start=now + timedelta(hours=2))

    result = _book(engine, student, session, now)

    assert result.ok, result.message


def test_r3_3_booking_closes_two_hours_before_start(engine, now):
    _, student, session, _ = _setup(
        engine, now, start=now + timedelta(hours=1, minutes=59)
    )
    before = _written(engine)

    result = _book(engine, student, session, now)

    assert result.code == Code.CLOSED
    assert _written(engine) == before


def test_r3_4_no_credits_refused(engine, now):
    _, student, session, _ = _setup(engine, now, credits=0)
    before = _written(engine)

    result = _book(engine, student, session, now)

    assert result.code == Code.NO_CREDITS
    assert _written(engine) == before


def _tomorrow_at(now, hour, minute=0):
    return (now + timedelta(days=1)).replace(hour=hour, minute=minute)


def test_r3_5_overlapping_booking_clashes_and_names_its_start(engine, now):
    instructor, student, first, _ = _setup(
        engine, now, start=_tomorrow_at(now, 10), credits=2, duration_min=90
    )
    make_booking(engine, student, first)
    overlapping = make_session(engine, instructor, _tomorrow_at(now, 11), duration_min=60)
    before = _written(engine)

    result = _book(engine, student, overlapping, now)

    assert result.code == Code.CLASH
    assert "10:00" in result.message
    assert _written(engine) == before


def test_r3_5_back_to_back_session_is_allowed(engine, now):
    instructor, student, first, _ = _setup(
        engine, now, start=_tomorrow_at(now, 10), credits=2, duration_min=90
    )
    make_booking(engine, student, first)
    next_one = make_session(engine, instructor, _tomorrow_at(now, 11, 30), duration_min=60)

    result = _book(engine, student, next_one, now)

    assert result.ok, result.message


def test_r3_7_booking_same_session_twice_is_duplicate(engine, now):
    _, student, session, _ = _setup(engine, now, credits=2)
    assert _book(engine, student, session, now).ok

    result = _book(engine, student, session, now)

    assert result.code == Code.DUPLICATE
    assert _count(engine, schema.bookings, member_id=student) == 1
    assert _balance(engine, student) == 1


def test_r3_8_last_place_goes_to_first_booker_then_full(engine, now):
    _, first, session, _ = _setup(engine, now, capacity=2)
    make_booking(engine, first, session)
    ana = make_member(engine, name="Ana")
    bruno = make_member(engine, name="Bruno")
    give_credits(engine, ana, 1)
    give_credits(engine, bruno, 1)

    ana_result = _book(engine, ana, session, now)
    bruno_result = _book(engine, bruno, session, now)

    assert ana_result.ok, ana_result.message
    assert bruno_result.code == Code.FULL
    assert bruno_result.data["can_join_waitlist"] is True
    assert _booked_count(engine, session) == 2
    assert _balance(engine, bruno) == 1
    assert _count(engine, schema.bookings, member_id=bruno) == 0


def test_r3_9_waiting_student_who_books_leaves_waitlist(engine, now):
    _, student, session, _ = _setup(engine, now)
    entry = add_waiting(engine, student, session, now - timedelta(hours=1))

    result = _book(engine, student, session, now)

    assert result.ok, result.message
    w = schema.waitlist_entries
    with engine.connect() as conn:
        status = conn.execute(select(w.c.status).where(w.c.id == entry)).scalar_one()
    assert status == "promoted"
    assert _count(engine, w, member_id=student, status="waiting") == 0


def test_unknown_session_is_not_found(engine, now):
    _, student, _, _ = _setup(engine, now)

    result = _book(engine, student, 9999, now)

    assert result.code == Code.NOT_FOUND


def test_unknown_actor_is_not_found(engine, now):
    _, _, session, _ = _setup(engine, now)

    result = _book(engine, 9999, session, now)

    assert result.code == Code.NOT_FOUND
