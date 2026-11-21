"""Service tests for creating, editing, deleting and listing surf sessions.

The fixed `now` is Fri 20 Nov 2026, 09:00 UTC; Lisbon equals UTC from
November to March, so local and stored times read the same here.
"""

from datetime import date, datetime, time

from sqlalchemy import select

from lineup import schema
from lineup.models import Code, SessionStatus
from lineup.services import booking
from lineup.services import sessions as svc
from tests.conftest import add_waiting, give_credits, make_booking, make_member, make_session

TOMORROW = date(2026, 11, 21)


def _row(engine, session_id):
    s = schema.surf_sessions
    with engine.connect() as conn:
        return conn.execute(select(s).where(s.c.id == session_id)).first()


def _session_count(engine):
    with engine.connect() as conn:
        return len(conn.execute(select(schema.surf_sessions.c.id)).all())


def _create(engine, actor_id, now, start=time(10, 0), day=TOMORROW, duration_min=90,
            capacity=4, level="beginner"):
    return svc.create_session(engine, actor_id, day, start, duration_min, capacity, level, now=now)


def _booked(engine, session_id, n=1):
    for _ in range(n):
        student = make_member(engine)
        give_credits(engine, student, 1)
        make_booking(engine, student, session_id)


# --- create ---------------------------------------------------------------

def test_r2_create_by_instructor_ok(engine, now):
    instructor = make_member(engine, role="instructor")
    result = _create(engine, instructor, now)
    assert result.ok, result.message
    row = _row(engine, result.data["session_id"])
    assert row.instructor_id == instructor
    assert row.starts_at == datetime(2026, 11, 21, 10, 0)
    assert row.duration_min == 90
    assert row.capacity == 4
    assert row.level == "beginner"
    assert row.status == SessionStatus.SCHEDULED.value
    assert row.booked_count == 0


def test_section3_student_cannot_create(engine, now):
    student = make_member(engine, role="student")
    result = _create(engine, student, now)
    assert result.code == Code.FORBIDDEN
    assert _session_count(engine) == 0


def test_section3_admin_cannot_create(engine, now):
    admin = make_member(engine, role="admin")
    result = _create(engine, admin, now)
    assert result.code == Code.FORBIDDEN
    assert _session_count(engine) == 0


def test_r2_1_start_off_step_rejected(engine, now):
    instructor = make_member(engine, role="instructor")
    assert _create(engine, instructor, now, start=time(8, 10)).code == Code.INVALID
    assert _session_count(engine) == 0


def test_r2_2_start_under_three_hours_rejected(engine, now):
    instructor = make_member(engine, role="instructor")
    result = _create(engine, instructor, now, day=date(2026, 11, 20), start=time(11, 45))
    assert result.code == Code.INVALID
    assert _session_count(engine) == 0


def test_r2_3_duration_45_rejected(engine, now):
    instructor = make_member(engine, role="instructor")
    assert _create(engine, instructor, now, duration_min=45).code == Code.INVALID


def test_r2_4_capacity_9_rejected(engine, now):
    instructor = make_member(engine, role="instructor")
    assert _create(engine, instructor, now, capacity=9).code == Code.INVALID


def test_r2_5_unknown_level_rejected(engine, now):
    instructor = make_member(engine, role="instructor")
    assert _create(engine, instructor, now, level="expert").code == Code.INVALID


def test_r2_6_overlap_own_scheduled_clash(engine, now):
    instructor = make_member(engine, role="instructor")
    make_session(engine, instructor, datetime(2026, 11, 21, 10, 0), duration_min=90)
    result = _create(engine, instructor, now, start=time(11, 0))
    assert result.code == Code.CLASH
    assert _session_count(engine) == 1


def test_r2_6_back_to_back_ok(engine, now):
    instructor = make_member(engine, role="instructor")
    make_session(engine, instructor, datetime(2026, 11, 21, 10, 0), duration_min=90)
    assert _create(engine, instructor, now, start=time(11, 30)).ok


def test_r2_6_same_time_other_instructor_ok(engine, now):
    first = make_member(engine, role="instructor")
    second = make_member(engine, role="instructor")
    make_session(engine, first, datetime(2026, 11, 21, 10, 0), duration_min=90)
    assert _create(engine, second, now, start=time(10, 0)).ok


def test_r2_6_overlap_own_called_off_ok(engine, now):
    instructor = make_member(engine, role="instructor")
    make_session(engine, instructor, datetime(2026, 11, 21, 10, 0), duration_min=90,
                 status="called_off")
    assert _create(engine, instructor, now, start=time(10, 0)).ok


# --- edit -----------------------------------------------------------------

def test_section3_edit_other_instructors_session_forbidden(engine, now):
    owner = make_member(engine, role="instructor")
    other = make_member(engine, role="instructor")
    sid = make_session(engine, owner, datetime(2026, 11, 21, 10, 0))
    result = svc.edit_session(engine, other, sid, {"capacity": 6}, now=now)
    assert result.code == Code.FORBIDDEN
    assert _row(engine, sid).capacity == 4


def test_r2_9_time_change_with_booking_invalid(engine, now):
    instructor = make_member(engine, role="instructor")
    sid = make_session(engine, instructor, datetime(2026, 11, 21, 10, 0))
    _booked(engine, sid)
    result = svc.edit_session(engine, instructor, sid, {"start_time": time(12, 0)}, now=now)
    assert result.code == Code.INVALID
    assert _row(engine, sid).starts_at == datetime(2026, 11, 21, 10, 0)


def test_r2_9_capacity_up_with_booking_ok(engine, now):
    instructor = make_member(engine, role="instructor")
    sid = make_session(engine, instructor, datetime(2026, 11, 21, 10, 0), capacity=4)
    _booked(engine, sid)
    result = svc.edit_session(engine, instructor, sid, {"capacity": 6}, now=now)
    assert result.ok, result.message
    assert _row(engine, sid).capacity == 6


def test_r2_9_capacity_below_booked_invalid(engine, now):
    instructor = make_member(engine, role="instructor")
    sid = make_session(engine, instructor, datetime(2026, 11, 21, 10, 0), capacity=4)
    _booked(engine, sid, n=2)
    result = svc.edit_session(engine, instructor, sid, {"capacity": 1}, now=now)
    assert result.code == Code.INVALID
    assert _row(engine, sid).capacity == 4


def test_r2_9_edit_unknown_field_invalid(engine, now):
    instructor = make_member(engine, role="instructor")
    sid = make_session(engine, instructor, datetime(2026, 11, 21, 10, 0))
    result = svc.edit_session(engine, instructor, sid, {"instructor_id": 999}, now=now)
    assert result.code == Code.INVALID
    assert _row(engine, sid).instructor_id == instructor


def test_r2_10_capacity_up_calls_promote_waitlist_once(engine, now, monkeypatch):
    instructor = make_member(engine, role="instructor")
    sid = make_session(engine, instructor, datetime(2026, 11, 21, 10, 0), capacity=4)
    calls = []

    def spy(conn, session_id, when):
        calls.append(session_id)
        return []

    monkeypatch.setattr(booking, "promote_waitlist", spy)
    result = svc.edit_session(engine, instructor, sid, {"capacity": 6}, now=now)
    assert result.ok, result.message
    assert calls == [sid]


def test_r2_6_edit_time_into_own_session_clash(engine, now):
    instructor = make_member(engine, role="instructor")
    make_session(engine, instructor, datetime(2026, 11, 21, 10, 0), duration_min=90)
    sid = make_session(engine, instructor, datetime(2026, 11, 21, 13, 0), duration_min=90)
    result = svc.edit_session(engine, instructor, sid, {"start_time": time(11, 0)}, now=now)
    assert result.code == Code.CLASH
    assert _row(engine, sid).starts_at == datetime(2026, 11, 21, 13, 0)


def test_r2_8_edit_after_start_closed(engine, now):
    instructor = make_member(engine, role="instructor")
    sid = make_session(engine, instructor, datetime(2026, 11, 20, 8, 0))
    result = svc.edit_session(engine, instructor, sid, {"capacity": 6}, now=now)
    assert result.code == Code.CLOSED
    assert _row(engine, sid).capacity == 4


# --- delete ---------------------------------------------------------------

def test_r2_11_delete_with_no_history_removes_row(engine, now):
    instructor = make_member(engine, role="instructor")
    sid = make_session(engine, instructor, datetime(2026, 11, 21, 10, 0))
    result = svc.delete_session(engine, instructor, sid, now=now)
    assert result.ok, result.message
    assert _row(engine, sid) is None


def test_r2_11_delete_with_booking_invalid(engine, now):
    instructor = make_member(engine, role="instructor")
    sid = make_session(engine, instructor, datetime(2026, 11, 21, 10, 0))
    _booked(engine, sid)
    result = svc.delete_session(engine, instructor, sid, now=now)
    assert result.code == Code.INVALID
    assert _row(engine, sid) is not None


def test_r2_11_delete_with_waitlist_history_invalid(engine, now):
    instructor = make_member(engine, role="instructor")
    sid = make_session(engine, instructor, datetime(2026, 11, 21, 10, 0))
    add_waiting(engine, make_member(engine), sid, now)
    result = svc.delete_session(engine, instructor, sid, now=now)
    assert result.code == Code.INVALID
    assert _row(engine, sid) is not None


def test_section3_delete_other_instructors_session_forbidden(engine, now):
    owner = make_member(engine, role="instructor")
    other = make_member(engine, role="instructor")
    sid = make_session(engine, owner, datetime(2026, 11, 21, 10, 0))
    result = svc.delete_session(engine, other, sid, now=now)
    assert result.code == Code.FORBIDDEN
    assert _row(engine, sid) is not None


# --- list -----------------------------------------------------------------

def test_list_my_sessions_only_own_upcoming(engine, now):
    instructor = make_member(engine, role="instructor")
    other = make_member(engine, role="instructor")
    make_session(engine, instructor, datetime(2026, 11, 19, 10, 0))
    later = make_session(engine, instructor, datetime(2026, 11, 22, 10, 0), status="called_off")
    sooner = make_session(engine, instructor, datetime(2026, 11, 21, 10, 0), capacity=5)
    make_session(engine, other, datetime(2026, 11, 21, 10, 0))
    _booked(engine, sooner)

    result = svc.list_my_sessions(engine, instructor, now=now)
    assert result.ok, result.message
    assert [s.id for s in result.data] == [sooner, later]
    first = result.data[0]
    assert (first.booked_count, first.capacity) == (1, 5)
    assert result.data[1].status == SessionStatus.CALLED_OFF


def test_list_my_sessions_includes_late_on_last_day(engine, now):
    instructor = make_member(engine, role="instructor")
    late = make_session(engine, instructor, datetime(2026, 12, 4, 22, 0))
    make_session(engine, instructor, datetime(2026, 12, 5, 8, 0))
    result = svc.list_my_sessions(engine, instructor, now=now)
    assert result.ok, result.message
    assert [s.id for s in result.data] == [late]


# --- R2.7 end by sunset, or by 17:00 without sunset data -------------------

def _save_sunset(engine, day, sunset_utc, fetched_at):
    with engine.begin() as conn:
        conn.execute(schema.forecast_days.insert().values(
            day=day, sunset_utc=sunset_utc, fetched_at=fetched_at,
        ))


def test_r2_7_create_ending_at_sunset_ok(engine, now):
    instructor = make_member(engine, role="instructor")
    _save_sunset(engine, TOMORROW, datetime(2026, 11, 21, 17, 15), now)
    result = _create(engine, instructor, now, start=time(15, 45), duration_min=90)
    assert result.ok, result.message


def test_r2_7_create_ending_after_sunset_invalid(engine, now):
    instructor = make_member(engine, role="instructor")
    _save_sunset(engine, TOMORROW, datetime(2026, 11, 21, 17, 15), now)
    result = _create(engine, instructor, now, start=time(16, 0), duration_min=90)
    assert result.code == Code.INVALID
    assert "sunset" in result.message
    assert "17:15" in result.message
    assert _session_count(engine) == 0


def test_r2_7_no_sunset_data_ending_at_1700_ok(engine, now):
    instructor = make_member(engine, role="instructor")
    result = _create(engine, instructor, now, start=time(15, 30), duration_min=90)
    assert result.ok, result.message


def test_r2_7_no_sunset_data_ending_after_1700_invalid(engine, now):
    instructor = make_member(engine, role="instructor")
    result = _create(engine, instructor, now, start=time(15, 45), duration_min=90)
    assert result.code == Code.INVALID
    assert "17:00" in result.message
    assert "no sunset data" in result.message
    assert _session_count(engine) == 0


def test_r2_7_edit_moving_end_after_sunset_invalid(engine, now):
    instructor = make_member(engine, role="instructor")
    _save_sunset(engine, TOMORROW, datetime(2026, 11, 21, 17, 15), now)
    sid = _create(engine, instructor, now).data["session_id"]
    result = svc.edit_session(engine, instructor, sid, {"start_time": time(16, 0)}, now=now)
    assert result.code == Code.INVALID
    assert "sunset" in result.message
    assert _row(engine, sid).starts_at == datetime(2026, 11, 21, 10, 0)


def test_r2_7_capacity_only_edit_is_not_rechecked_against_latest_end(engine, now):
    instructor = make_member(engine, role="instructor")
    # Inserted directly: it ends at 17:30, past the 17:00 fallback limit.
    sid = make_session(engine, instructor, datetime(2026, 11, 21, 16, 0), duration_min=90)
    result = svc.edit_session(engine, instructor, sid, {"capacity": 6}, now=now)
    assert result.ok, result.message
    assert _row(engine, sid).capacity == 6


# --- R2.10 end to end with the real waitlist promotion ---------------------

def test_r2_10_two_places_added_books_both_waiting_students(engine, now):
    from lineup import db

    instructor = make_member(engine, role="instructor")
    sid = make_session(engine, instructor, datetime(2026, 11, 21, 10, 0), capacity=2)
    _booked(engine, sid, n=2)
    waiting = [make_member(engine), make_member(engine)]
    for i, member in enumerate(waiting):
        give_credits(engine, member, 1)
        add_waiting(engine, member, sid, datetime(2026, 11, 20, 8, i))

    result = svc.edit_session(engine, instructor, sid, {"capacity": 4}, now=now)

    assert result.ok, result.message
    b = schema.bookings
    with engine.connect() as conn:
        booked = conn.execute(
            select(b.c.member_id).where(b.c.session_id == sid, b.c.status == "confirmed")
        ).scalars().all()
        balances = [db.ledger_balance(conn, member) for member in waiting]
    assert set(waiting) <= set(booked)
    assert balances == [0, 0]
    assert _row(engine, sid).booked_count == 4
