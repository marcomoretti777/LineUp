"""Service tests for cancelling a booking (R5.1-R5.4, R10.8)."""

from datetime import timedelta

from conftest import give_credits, make_booking, make_member, make_session
from sqlalchemy import func, select

from lineup import db, schema
from lineup.models import Code


def _cancel(engine, actor_id, booking_id, now):
    # Imported here so a missing service fails each test, not collection.
    from lineup.services.booking import cancel_booking

    return cancel_booking(engine, actor_id, booking_id, now=now)


def _preview(engine, actor_id, booking_id, now):
    from lineup.services.booking import cancel_preview

    return cancel_preview(engine, actor_id, booking_id, now=now)


def _setup(engine, start):
    instructor = make_member(engine, role="instructor")
    student = make_member(engine)
    give_credits(engine, student, 1)
    session = make_session(engine, instructor, start)
    booking = make_booking(engine, student, session)
    return student, session, booking


def _balance(engine, member_id):
    with engine.connect() as conn:
        return db.ledger_balance(conn, member_id)


def _booked_count(engine, session_id):
    s = schema.surf_sessions
    with engine.connect() as conn:
        return conn.execute(select(s.c.booked_count).where(s.c.id == session_id)).scalar_one()


def _ledger_rows(engine, ref):
    ledger = schema.credit_ledger
    with engine.connect() as conn:
        return conn.execute(
            select(ledger.c.delta, ledger.c.kind).where(ledger.c.ref == ref)
        ).all()


def _ledger_count(engine):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(schema.credit_ledger)).scalar_one()


def _booking_row(engine, booking_id):
    b = schema.bookings
    with engine.connect() as conn:
        return conn.execute(select(b).where(b.c.id == booking_id)).one()


def test_r5_2_cancel_at_exactly_24_hours_before_start_refunds_one_credit(engine, now):
    student, _, booking = _setup(engine, now + timedelta(hours=24))

    result = _cancel(engine, student, booking, now)

    assert result.ok, result.message
    assert _balance(engine, student) == 1
    assert [(r.delta, r.kind) for r in _ledger_rows(engine, f"refund:{booking}")] == [
        (1, "refund")
    ]
    assert _booking_row(engine, booking).refunded is True


def test_r5_2_cancel_at_23_59_before_start_gives_no_refund(engine, now):
    student, _, booking = _setup(engine, now + timedelta(hours=23, minutes=59))

    result = _cancel(engine, student, booking, now)

    assert result.ok, result.message
    assert _ledger_rows(engine, f"refund:{booking}") == []
    assert _balance(engine, student) == 0
    assert _booking_row(engine, booking).refunded is False


def test_r5_1_cancel_at_start_time_is_closed(engine, now):
    student, session, booking = _setup(engine, now)

    result = _cancel(engine, student, booking, now)

    assert not result.ok
    assert result.code == Code.CLOSED
    assert _booking_row(engine, booking).status == "confirmed"
    assert _booked_count(engine, session) == 1


def test_r5_1_cancel_another_students_booking_is_forbidden(engine, now):
    _, session, booking = _setup(engine, now + timedelta(days=2))
    other = make_member(engine)

    result = _cancel(engine, other, booking, now)

    assert not result.ok
    assert result.code == Code.FORBIDDEN
    assert _booking_row(engine, booking).status == "confirmed"
    assert _booked_count(engine, session) == 1


def test_r5_1_cancel_unknown_booking_is_not_found(engine, now):
    student = make_member(engine)

    result = _cancel(engine, student, 9999, now)

    assert not result.ok
    assert result.code == Code.NOT_FOUND


def test_r5_4_cancel_twice_is_already_done_and_adds_no_ledger_row(engine, now):
    student, session, booking = _setup(engine, now + timedelta(days=2))
    assert _cancel(engine, student, booking, now).ok
    rows_after_first = _ledger_count(engine)

    result = _cancel(engine, student, booking, now)

    assert not result.ok
    assert result.code == Code.ALREADY_DONE
    assert _ledger_count(engine) == rows_after_first
    assert _balance(engine, student) == 1
    assert _booked_count(engine, session) == 0


def test_r5_3_cancel_marks_booking_cancelled_and_frees_the_place(engine, now):
    student, session, booking = _setup(engine, now + timedelta(days=2))
    assert _booked_count(engine, session) == 1

    result = _cancel(engine, student, booking, now)

    assert result.ok, result.message
    row = _booking_row(engine, booking)
    assert row.status == "cancelled"
    assert row.cancelled_at == now
    assert _booked_count(engine, session) == 0


def test_r5_3_cancel_runs_promote_waitlist_once_for_the_session(engine, now, monkeypatch):
    from lineup.services import booking as booking_service

    student, session, booking = _setup(engine, now + timedelta(days=2))
    calls = []
    monkeypatch.setattr(
        booking_service,
        "promote_waitlist",
        lambda conn, session_id, at: calls.append((session_id, at)) or [],
    )

    result = _cancel(engine, student, booking, now)

    assert result.ok, result.message
    assert calls == [(session, now)]


def test_r5_2_cancel_preview_own_booking_at_24_00_says_refund(engine, now):
    start = now + timedelta(hours=24)
    student, _, booking = _setup(engine, start)

    result = _preview(engine, student, booking, now)

    assert result.ok, result.message
    assert result.data == {"refund": True, "refund_deadline": start - timedelta(hours=24)}


def test_r5_2_cancel_preview_own_booking_at_23_59_says_no_refund(engine, now):
    start = now + timedelta(hours=23, minutes=59)
    student, _, booking = _setup(engine, start)

    result = _preview(engine, student, booking, now)

    assert result.ok, result.message
    assert result.data == {"refund": False, "refund_deadline": start - timedelta(hours=24)}


def test_r5_1_cancel_preview_someone_elses_booking_is_forbidden(engine, now):
    _, _, booking = _setup(engine, now + timedelta(days=2))
    other = make_member(engine)

    result = _preview(engine, other, booking, now)

    assert not result.ok
    assert result.code == Code.FORBIDDEN
