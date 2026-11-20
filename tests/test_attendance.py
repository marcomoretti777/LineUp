"""Tests for attendance marking, the roster and formula-safe CSV (R9.1-R9.3, R12.7, R12.8)."""

import csv
import io
from datetime import timedelta

import pytest
from conftest import add_waiting, give_credits, make_booking, make_member, make_session
from sqlalchemy import func, select, update

from lineup import db, schema
from lineup.models import Code

ROSTER_HEADER = ["session_start", "student", "email", "level", "status", "attendance"]


# Services are imported inside these helpers so a missing module fails each
# test on its own instead of stopping collection.

def _mark(engine, actor_id, booking_id, value, now):
    from lineup.services.attendance import mark_attendance

    return mark_attendance(engine, actor_id, booking_id, value, now=now)


def _roster(engine, actor_id, session_id):
    from lineup.services.attendance import roster

    return roster(engine, actor_id, session_id)


def _roster_csv(engine, actor_id, session_id):
    from lineup.services.attendance import roster_csv

    return roster_csv(engine, actor_id, session_id)


def _attendance(engine, booking_id):
    b = schema.bookings
    with engine.connect() as conn:
        return conn.execute(select(b.c.attendance).where(b.c.id == booking_id)).scalar_one()


def _set_attendance(engine, booking_id, value):
    with engine.begin() as conn:
        conn.execute(
            update(schema.bookings).where(schema.bookings.c.id == booking_id)
            .values(attendance=value)
        )


def _ledger_rows(engine):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(schema.credit_ledger)).scalar_one()


def _call_off(engine, session_id, booking_id, at):
    # Keeps the invariants: no confirmed bookings in a called-off session.
    s, b = schema.surf_sessions, schema.bookings
    with engine.begin() as conn:
        conn.execute(update(b).where(b.c.id == booking_id).values(status="called_off"))
        conn.execute(
            update(s).where(s.c.id == session_id).values(
                status="called_off", booked_count=0, call_off_category="conditions",
                call_off_reason="Big swell", called_off_at=at,
            )
        )


def _booked_student(engine, session_id, **member):
    student = make_member(engine, **member)
    give_credits(engine, student, 1)
    return student, make_booking(engine, student, session_id)


@pytest.fixture
def setup(engine, now):
    """Instructor A's Beginner session at 10:00 (an hour after `now`) with one booking."""
    instructor = make_member(engine, role="instructor")
    start = now + timedelta(hours=1)
    session_id = make_session(engine, instructor, start)
    student, booking_id = _booked_student(engine, session_id)
    return {"instructor": instructor, "session": session_id, "start": start,
            "student": student, "booking": booking_id}


def _parse(data):
    return list(csv.reader(io.StringIO(data.decode("utf-8"))))


# ---------- R9.1 who and when ----------

def test_r9_1_mark_before_start_is_not_yet(engine, setup):
    one_minute_early = setup["start"] - timedelta(minutes=1)

    result = _mark(engine, setup["instructor"], setup["booking"], "attended", one_minute_early)

    assert not result.ok
    assert result.code == Code.NOT_YET
    assert _attendance(engine, setup["booking"]) is None


def test_r9_1_own_instructor_can_mark_from_start(engine, setup):
    result = _mark(engine, setup["instructor"], setup["booking"], "attended", setup["start"])

    assert result.ok
    assert _attendance(engine, setup["booking"]) == "attended"


def test_r9_1_mark_called_off_session_is_closed(engine, setup):
    _call_off(engine, setup["session"], setup["booking"], setup["start"] - timedelta(hours=2))

    result = _mark(engine, setup["instructor"], setup["booking"], "attended",
                   setup["start"] + timedelta(minutes=30))

    assert not result.ok
    assert result.code == Code.CLOSED
    assert _attendance(engine, setup["booking"]) is None


def test_r9_1_other_instructor_is_forbidden(engine, setup):
    other = make_member(engine, role="instructor")

    result = _mark(engine, other, setup["booking"], "attended", setup["start"])

    assert not result.ok
    assert result.code == Code.FORBIDDEN
    assert _attendance(engine, setup["booking"]) is None


def test_r9_1_admin_can_mark_any_session(engine, setup):
    admin = make_member(engine, role="admin")

    result = _mark(engine, admin, setup["booking"], "attended", setup["start"])

    assert result.ok
    assert _attendance(engine, setup["booking"]) == "attended"


def test_r9_1_student_is_forbidden(engine, setup):
    result = _mark(engine, setup["student"], setup["booking"], "attended", setup["start"])

    assert not result.ok
    assert result.code == Code.FORBIDDEN
    assert _attendance(engine, setup["booking"]) is None


# ---------- R9.2 correction ----------

def test_r9_2_attended_corrected_to_no_show_is_saved(engine, setup):
    later = setup["start"] + timedelta(hours=3)

    first = _mark(engine, setup["instructor"], setup["booking"], "attended", setup["start"])
    second = _mark(engine, setup["instructor"], setup["booking"], "no_show", later)

    assert first.ok
    assert second.ok
    assert _attendance(engine, setup["booking"]) == "no_show"


# ---------- R9.3 no refund for a no-show ----------

def test_r9_3_no_show_writes_no_ledger_row(engine, setup):
    rows_before = _ledger_rows(engine)
    with engine.connect() as conn:
        balance_before = db.ledger_balance(conn, setup["student"])

    result = _mark(engine, setup["instructor"], setup["booking"], "no_show", setup["start"])

    assert result.ok
    assert _ledger_rows(engine) == rows_before
    with engine.connect() as conn:
        assert db.ledger_balance(conn, setup["student"]) == balance_before


# ---------- roster ----------

def test_roster_own_session_lists_booked_and_waitlist_in_order(engine, now):
    instructor = make_member(engine, role="instructor")
    session_id = make_session(engine, instructor, now + timedelta(hours=1), capacity=2)
    _, bruno_booking = _booked_student(engine, session_id, name="Bruno Dias",
                                       email="bruno@novasbe.pt")
    _booked_student(engine, session_id, name="Ana Costa", email="ana@novasbe.pt",
                    level="intermediate")
    _set_attendance(engine, bruno_booking, "attended")
    late = make_member(engine, name="Late Joiner")
    early = make_member(engine, name="Early Joiner")
    add_waiting(engine, late, session_id, now - timedelta(minutes=5))
    add_waiting(engine, early, session_id, now - timedelta(hours=1))

    result = _roster(engine, instructor, session_id)

    assert result.ok
    booked = result.data["booked"]
    assert [r["name"] for r in booked] == ["Ana Costa", "Bruno Dias"]
    assert booked[0]["email"] == "ana@novasbe.pt"
    assert booked[0]["level"] == "intermediate"
    assert booked[0]["beginner_attended"] == 0
    assert booked[0]["attendance"] is None
    assert booked[1]["attendance"] == "attended"
    assert [w["member_id"] for w in result.data["waitlist"]] == [early, late]


def test_roster_attended_beginner_count(engine, now):
    instructor = make_member(engine, role="instructor")
    student = make_member(engine, name="Rita Sousa")
    give_credits(engine, student, 5)
    # Past sessions on different days, so the student never has a clash.
    for days, level, mark in [(3, "beginner", "attended"), (4, "beginner", "attended"),
                              (5, "beginner", "no_show"), (6, "intermediate", "attended")]:
        past = make_session(engine, instructor, now - timedelta(days=days), level=level)
        _set_attendance(engine, make_booking(engine, student, past), mark)
    session_id = make_session(engine, instructor, now + timedelta(hours=1))
    make_booking(engine, student, session_id)

    result = _roster(engine, instructor, session_id)

    assert result.ok
    assert result.data["booked"][0]["beginner_attended"] == 2


def test_roster_other_instructor_is_forbidden(engine, setup):
    other = make_member(engine, role="instructor")

    result = _roster(engine, other, setup["session"])

    assert not result.ok
    assert result.code == Code.FORBIDDEN


# ---------- R12.7 safe CSV ----------

def test_r12_7_roster_csv_header_is_exact(engine, setup):
    result = _roster_csv(engine, setup["instructor"], setup["session"])

    assert result.ok
    assert isinstance(result.data, bytes)
    assert _parse(result.data)[0] == ROSTER_HEADER


def test_r12_7_roster_csv_escapes_formula_name(engine, setup):
    _booked_student(engine, setup["session"], name="=SUM(A1)")

    result = _roster_csv(engine, setup["instructor"], setup["session"])

    assert result.ok
    students = [row[1] for row in _parse(result.data)[1:]]
    assert "'=SUM(A1)" in students
    assert "=SUM(A1)" not in students


@pytest.mark.parametrize("value", ["=HYPERLINK(\"x\")", "+1", "-2", "@cmd"])
def test_r12_7_csv_safe_prefixes_formula_starts(value):
    from lineup.logic.reports import csv_safe

    assert csv_safe(value) == "'" + value


@pytest.mark.parametrize("value, expected", [
    ("Ana", "Ana"), ("", ""), ("a=b", "a=b"), (3, 3), (None, ""),
])
def test_r12_7_csv_safe_leaves_other_values(value, expected):
    from lineup.logic.reports import csv_safe

    assert csv_safe(value) == expected


# ---------- R12.8 export permissions ----------

def test_r12_8_student_cannot_export_roster(engine, setup):
    result = _roster_csv(engine, setup["student"], setup["session"])

    assert not result.ok
    assert result.code == Code.FORBIDDEN


# ---------- roster session picker ----------

def _roster_sessions(engine, actor_id, now):
    from lineup.services.attendance import roster_sessions

    return roster_sessions(engine, actor_id, now=now)


def test_roster_sessions_instructor_sees_own_from_last_7_days(engine, now):
    tiago = make_member(engine, role="instructor")
    other = make_member(engine, role="instructor")
    too_old = make_session(engine, tiago, now - timedelta(days=8))
    last_week = make_session(engine, tiago, now - timedelta(days=6))
    called_off = make_session(engine, tiago, now - timedelta(days=2), status="called_off")
    upcoming = make_session(engine, tiago, now + timedelta(days=3))
    make_session(engine, other, now + timedelta(days=1))

    result = _roster_sessions(engine, tiago, now)

    assert result.ok
    assert [s.id for s in result.data] == [last_week, called_off, upcoming]
    assert too_old not in [s.id for s in result.data]


def test_roster_sessions_admin_sees_every_instructor(engine, now):
    admin = make_member(engine, role="admin")
    a = make_session(engine, make_member(engine, role="instructor"), now + timedelta(hours=1))
    b = make_session(engine, make_member(engine, role="instructor"), now - timedelta(days=1))

    result = _roster_sessions(engine, admin, now)

    assert result.ok
    assert [s.id for s in result.data] == [b, a]


def test_roster_sessions_student_is_forbidden(engine, now):
    student = make_member(engine)

    result = _roster_sessions(engine, student, now)

    assert not result.ok
    assert result.code == Code.FORBIDDEN
