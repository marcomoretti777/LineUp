"""Call-off (R8.1-R8.5, R10.8, R11.1) and the "Needs your decision" list.

The services are imported inside each test, so a missing function fails
only that test instead of breaking collection of the whole file.
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from lineup import db, schema
from lineup.models import Code, Condition, Label
from tests.conftest import add_waiting, give_credits, make_booking, make_member, make_session

REASON = "Wind over 40 km/h"


def _call_off(engine, actor_id, session_id, now, category="conditions", reason=REASON):
    from lineup.services.sessions import call_off

    return call_off(engine, actor_id, session_id, category, reason, now=now)


def _count(engine, table):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def _session_row(engine, session_id):
    s = schema.surf_sessions
    with engine.connect() as conn:
        return conn.execute(select(s).where(s.c.id == session_id)).one()


def _booked_session(engine, now, students=3, start_in=timedelta(days=2)):
    instructor = make_member(engine, role="instructor")
    session = make_session(engine, instructor, now + start_in)
    members, bookings = [], []
    for _ in range(students):
        member = make_member(engine)
        give_credits(engine, member, 1)
        members.append(member)
        bookings.append(make_booking(engine, member, session))
    return instructor, session, members, bookings


# R8.1: who may call off, and until when.

def test_r8_1_own_instructor_can_call_off(engine, now):
    instructor = make_member(engine, role="instructor")
    session = make_session(engine, instructor, now + timedelta(days=1))

    result = _call_off(engine, instructor, session, now)

    assert result.ok, result.message
    assert _session_row(engine, session).status == "called_off"


def test_r8_1_other_instructor_is_forbidden(engine, now):
    instructor, session, _, _ = _booked_session(engine, now, students=1)
    other = make_member(engine, role="instructor")
    ledger_before = _count(engine, schema.credit_ledger)

    result = _call_off(engine, other, session, now)

    assert result.code == Code.FORBIDDEN
    assert _session_row(engine, session).status == "scheduled"
    assert _count(engine, schema.credit_ledger) == ledger_before
    assert _count(engine, schema.notifications) == 0


def test_r8_1_admin_can_call_off_any_session(engine, now):
    instructor = make_member(engine, role="instructor")
    admin = make_member(engine, role="admin")
    session = make_session(engine, instructor, now + timedelta(days=1))

    result = _call_off(engine, admin, session, now)

    assert result.ok, result.message
    assert _session_row(engine, session).status == "called_off"


def test_r8_1_student_is_forbidden(engine, now):
    instructor = make_member(engine, role="instructor")
    student = make_member(engine)
    session = make_session(engine, instructor, now + timedelta(days=1))

    result = _call_off(engine, student, session, now)

    assert result.code == Code.FORBIDDEN
    assert _session_row(engine, session).status == "scheduled"


def test_r8_1_after_session_end_is_closed(engine, now):
    instructor = make_member(engine, role="instructor")
    session = make_session(engine, instructor, now - timedelta(minutes=90), duration_min=90)

    result = _call_off(engine, instructor, session, now)

    assert result.code == Code.CLOSED
    assert _session_row(engine, session).status == "scheduled"


def test_r8_1_while_running_is_allowed(engine, now):
    instructor = make_member(engine, role="instructor")
    session = make_session(engine, instructor, now - timedelta(minutes=89), duration_min=90)

    result = _call_off(engine, instructor, session, now)

    assert result.ok, result.message


# R8.2: category and reason.

def test_r8_2_unknown_category_is_invalid(engine, now):
    instructor = make_member(engine, role="instructor")
    session = make_session(engine, instructor, now + timedelta(days=1))

    result = _call_off(engine, instructor, session, now, category="weather")

    assert result.code == Code.INVALID
    assert _session_row(engine, session).status == "scheduled"


@pytest.mark.parametrize("length, ok", [(2, False), (3, True), (200, True), (201, False)])
def test_r8_2_reason_length(engine, now, length, ok):
    instructor = make_member(engine, role="instructor")
    session = make_session(engine, instructor, now + timedelta(days=1))

    result = _call_off(engine, instructor, session, now, reason="x" * length)

    if ok:
        assert result.ok, result.message
    else:
        assert result.code == Code.INVALID
        assert _session_row(engine, session).status == "scheduled"


# R8.3, R10.8: every confirmed booking is refunded exactly once.

def test_r8_3_every_confirmed_booking_refunded_once(engine, now):
    # Starts in 1 h, well inside the 24 h window, so a refund here ignores timing.
    instructor, session, members, bookings = _booked_session(
        engine, now, students=3, start_in=timedelta(hours=1)
    )

    result = _call_off(engine, instructor, session, now)

    assert result.ok, result.message
    b, ledger = schema.bookings, schema.credit_ledger
    with engine.connect() as conn:
        rows = conn.execute(select(b.c.id, b.c.status, b.c.refunded)
                            .where(b.c.session_id == session)).all()
        assert {r.id for r in rows} == set(bookings)
        assert all(r.status == "called_off" and r.refunded for r in rows)
        for booking_id, member in zip(bookings, members):
            refunds = conn.execute(
                select(ledger.c.member_id, ledger.c.delta, ledger.c.kind)
                .where(ledger.c.ref == f"refund:{booking_id}")
            ).all()
            assert [tuple(r) for r in refunds] == [(member, 1, "refund")]
            assert db.ledger_balance(conn, member) == 1
    assert _session_row(engine, session).booked_count == 0


# R8.4, R11.1: the waitlist is cleared and every student is told.

def test_r8_4_waitlist_cleared_and_everyone_notified(engine, now):
    instructor, session, members, _ = _booked_session(engine, now, students=3)
    waiting = [make_member(engine), make_member(engine)]
    entries = [add_waiting(engine, m, session, now - timedelta(hours=i + 1))
               for i, m in enumerate(waiting)]

    result = _call_off(engine, instructor, session, now)

    assert result.ok, result.message
    w, n = schema.waitlist_entries, schema.notifications
    with engine.connect() as conn:
        statuses = conn.execute(select(w.c.status).where(w.c.id.in_(entries))).scalars().all()
        notes = conn.execute(select(n.c.member_id, n.c.kind)).all()
    assert statuses == ["cleared", "cleared"]
    assert len(notes) == 5
    assert sorted(r.member_id for r in notes) == sorted(members + waiting)
    assert {r.kind for r in notes} == {"called_off"}


# R8.5: a second call-off changes nothing.

def test_r8_5_calling_off_twice_changes_nothing(engine, now):
    instructor, session, _, _ = _booked_session(engine, now, students=3)
    add_waiting(engine, make_member(engine), session, now - timedelta(hours=1))
    assert _call_off(engine, instructor, session, now).ok
    ledger_before = _count(engine, schema.credit_ledger)
    notes_before = _count(engine, schema.notifications)

    again = _call_off(engine, instructor, session, now + timedelta(minutes=5))

    assert again.code == Code.ALREADY_DONE
    assert _count(engine, schema.credit_ledger) == ledger_before
    assert _count(engine, schema.notifications) == notes_before


def test_r8_session_saves_category_reason_and_time(engine, now):
    instructor = make_member(engine, role="instructor")
    session = make_session(engine, instructor, now + timedelta(days=1))

    result = _call_off(engine, instructor, session, now, category="instructor_unavailable")

    assert result.ok, result.message
    row = _session_row(engine, session)
    assert row.status == "called_off"
    assert row.call_off_category == "instructor_unavailable"
    assert row.call_off_reason == REASON
    assert row.called_off_at == now


# "Needs your decision" (section 11, My sessions): own sessions in the next 72 h
# labelled No-go or Unknown.

def test_r8_decision_needed_lists_own_no_go_and_unknown_next_72h(engine, now):
    from lineup.services.sessions import decision_needed

    me = make_member(engine, role="instructor")
    other = make_member(engine, role="instructor")
    labels = {}

    def add(owner, start, label, status="scheduled"):
        session_id = make_session(engine, owner, start, status=status)
        labels[session_id] = Label(label)
        return session_id

    no_go_soon = add(me, now + timedelta(hours=5), "no_go")
    unknown = add(me, now + timedelta(hours=24), "unknown")
    add(me, now + timedelta(hours=30), "go")
    add(me, now + timedelta(hours=36), "marginal")
    add(me, now + timedelta(hours=72), "no_go")
    add(me, now - timedelta(hours=1), "no_go")
    add(me, now + timedelta(hours=48), "no_go", status="called_off")
    add(other, now + timedelta(hours=6), "no_go")

    def fake_conditions(engine, sessions, now=None):
        return {s.id: Condition(labels[s.id], None, None, "") for s in sessions}

    result = decision_needed(engine, me, now=now, conditions=fake_conditions)

    assert result.ok, result.message
    assert [(s.id, c.label) for s, c in result.data] == [
        (no_go_soon, Label.NO_GO), (unknown, Label.UNKNOWN),
    ]


def test_r8_decision_needed_student_is_forbidden(engine, now):
    from lineup.services.sessions import decision_needed

    student = make_member(engine)

    result = decision_needed(engine, student, now=now, conditions=lambda *a, **k: {})

    assert result.code == Code.FORBIDDEN
