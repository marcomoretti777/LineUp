"""Service tests for the waitlist: join, leave, position and promotion (R4.1-R4.6, R2.10, R11.1)."""

from datetime import timedelta

from conftest import add_waiting, give_credits, make_booking, make_member, make_session
from sqlalchemy import func, select, update

from lineup import db, schema
from lineup.models import Code


def _join(engine, actor_id, session_id, now):
    # Imported here so a missing service fails each test, not collection.
    from lineup.services.booking import join_waitlist

    return join_waitlist(engine, actor_id, session_id, now=now)


def _leave(engine, actor_id, entry_id, now):
    from lineup.services.booking import leave_waitlist

    return leave_waitlist(engine, actor_id, entry_id, now=now)


def _position(engine, actor_id, session_id):
    from lineup.services.booking import waitlist_position

    return waitlist_position(engine, actor_id, session_id)


def _cancel(engine, actor_id, booking_id, now):
    from lineup.services.booking import cancel_booking

    return cancel_booking(engine, actor_id, booking_id, now=now)


def _full_session(engine, start, capacity=1):
    # Returns the session and its (holder, booking) pairs, every place taken.
    instructor = make_member(engine, role="instructor")
    session = make_session(engine, instructor, start, capacity=capacity)
    holders = []
    for _ in range(capacity):
        holder = make_member(engine)
        give_credits(engine, holder, 1)
        holders.append((holder, make_booking(engine, holder, session)))
    return session, holders


def _student(engine, credits=0):
    student = make_member(engine)
    if credits:
        give_credits(engine, student, credits)
    return student


def _entry(engine, entry_id):
    w = schema.waitlist_entries
    with engine.connect() as conn:
        return conn.execute(
            select(w.c.status, w.c.reason, w.c.created_at).where(w.c.id == entry_id)
        ).one()


def _entries_for(engine, member_id, session_id):
    w = schema.waitlist_entries
    with engine.connect() as conn:
        return conn.execute(
            select(w.c.id, w.c.status, w.c.created_at)
            .where(w.c.member_id == member_id, w.c.session_id == session_id)
        ).all()


def _notifications(engine, member_id):
    n = schema.notifications
    with engine.connect() as conn:
        return conn.execute(
            select(n.c.kind, n.c.message).where(n.c.member_id == member_id).order_by(n.c.id)
        ).all()


def _balance(engine, member_id):
    with engine.connect() as conn:
        return db.ledger_balance(conn, member_id)


def _booked(engine, member_id, session_id):
    b = schema.bookings
    with engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(b).where(
                b.c.member_id == member_id, b.c.session_id == session_id,
                b.c.status == "confirmed",
            )
        ).scalar_one() == 1


def _booked_count(engine, session_id):
    s = schema.surf_sessions
    with engine.connect() as conn:
        return conn.execute(select(s.c.booked_count).where(s.c.id == session_id)).scalar_one()


# --- join_waitlist (R4.1) ---

def test_r4_1_join_with_places_left_is_not_full(engine, now):
    instructor = make_member(engine, role="instructor")
    session = make_session(engine, instructor, now + timedelta(days=2), capacity=2)
    student = _student(engine)

    result = _join(engine, student, session, now)

    assert not result.ok
    assert result.code == Code.NOT_FULL
    assert _entries_for(engine, student, session) == []


def test_r4_1_join_full_session_creates_waiting_entry(engine, now):
    session, _ = _full_session(engine, now + timedelta(days=2))
    student = _student(engine)

    result = _join(engine, student, session, now)

    assert result.ok, result.message
    entries = _entries_for(engine, student, session)
    assert len(entries) == 1
    assert entries[0].status == "waiting"
    assert entries[0].created_at == now
    assert result.data["entry_id"] == entries[0].id
    assert result.data["position"] == 1


def test_r4_1_join_twice_is_duplicate(engine, now):
    session, _ = _full_session(engine, now + timedelta(days=2))
    student = _student(engine)
    assert _join(engine, student, session, now).ok

    result = _join(engine, student, session, now)

    assert not result.ok
    assert result.code == Code.DUPLICATE
    assert len(_entries_for(engine, student, session)) == 1


def test_r4_1_booked_student_joining_is_duplicate(engine, now):
    session, [(holder, _)] = _full_session(engine, now + timedelta(days=2))

    result = _join(engine, holder, session, now)

    assert not result.ok
    assert result.code == Code.DUPLICATE
    assert _entries_for(engine, holder, session) == []


def test_r4_1_join_after_cutoff_is_closed(engine, now):
    session, _ = _full_session(engine, now + timedelta(hours=1, minutes=59))
    student = _student(engine)

    result = _join(engine, student, session, now)

    assert not result.ok
    assert result.code == Code.CLOSED
    assert _entries_for(engine, student, session) == []


def test_r4_1_join_with_clash_is_clash(engine, now):
    start = now + timedelta(days=2)
    session, _ = _full_session(engine, start)
    student = _student(engine, credits=1)
    other = make_session(engine, make_member(engine, role="instructor"),
                         start + timedelta(minutes=30))
    make_booking(engine, student, other)

    result = _join(engine, student, session, now)

    assert not result.ok
    assert result.code == Code.CLASH
    assert _entries_for(engine, student, session) == []


def test_r4_1_student_with_zero_credits_may_join(engine, now):
    session, _ = _full_session(engine, now + timedelta(days=2))
    student = _student(engine)
    assert _balance(engine, student) == 0

    result = _join(engine, student, session, now)

    assert result.ok, result.message
    assert _entries_for(engine, student, session)[0].status == "waiting"


# --- waitlist_position (R4.6) ---

def test_r4_6_third_in_line_has_position_3(engine, now):
    session, _ = _full_session(engine, now + timedelta(days=2))
    first, second, third = _student(engine), _student(engine), _student(engine)
    # Inserted out of order so the position must come from join time, not id.
    add_waiting(engine, third, session, now - timedelta(hours=1))
    add_waiting(engine, first, session, now - timedelta(hours=3))
    add_waiting(engine, second, session, now - timedelta(hours=2))

    assert _position(engine, third, session) == 3
    assert _position(engine, first, session) == 1


def test_r4_6_member_not_waiting_has_no_position(engine, now):
    session, _ = _full_session(engine, now + timedelta(days=2))
    add_waiting(engine, _student(engine), session, now - timedelta(hours=1))
    outsider = _student(engine)

    assert _position(engine, outsider, session) is None


# --- leave_waitlist (R4.5) ---

def test_r4_5_leave_own_entry_sets_status_left(engine, now):
    session, _ = _full_session(engine, now + timedelta(days=2))
    student = _student(engine)
    entry = add_waiting(engine, student, session, now - timedelta(hours=1))

    result = _leave(engine, student, entry, now)

    assert result.ok, result.message
    assert _entry(engine, entry).status == "left"
    assert _position(engine, student, session) is None


def test_r4_5_leave_someone_elses_entry_is_forbidden(engine, now):
    session, _ = _full_session(engine, now + timedelta(days=2))
    owner, intruder = _student(engine), _student(engine)
    entry = add_waiting(engine, owner, session, now - timedelta(hours=1))

    result = _leave(engine, intruder, entry, now)

    assert not result.ok
    assert result.code == Code.FORBIDDEN
    assert _entry(engine, entry).status == "waiting"


def test_r4_5_leave_after_start_is_closed(engine, now):
    start = now + timedelta(days=2)
    session, _ = _full_session(engine, start)
    student = _student(engine)
    entry = add_waiting(engine, student, session, now - timedelta(hours=1))

    result = _leave(engine, student, entry, start)

    assert not result.ok
    assert result.code == Code.CLOSED
    assert _entry(engine, entry).status == "waiting"


# --- promote_waitlist (R4.2, R4.3, R4.4, R11.1) ---

def test_r4_2_r4_3_freed_place_goes_to_earliest_waiting(engine, now):
    session, [(ana, ana_booking)] = _full_session(engine, now + timedelta(days=2))
    a, b = _student(engine, credits=1), _student(engine, credits=1)
    entry_a = add_waiting(engine, a, session, now - timedelta(hours=2))
    entry_b = add_waiting(engine, b, session, now - timedelta(hours=1))

    assert _cancel(engine, ana, ana_booking, now).ok

    assert _booked(engine, a, session)
    assert _balance(engine, a) == 0
    assert _entry(engine, entry_a).status == "promoted"
    [note] = _notifications(engine, a)
    assert note.message.startswith("You got a place")
    assert not _booked(engine, b, session)
    assert _entry(engine, entry_b).status == "waiting"
    assert _notifications(engine, b) == []
    assert _booked_count(engine, session) == 1


def test_r4_3_no_credit_first_in_line_removed_and_next_booked(engine, now):
    session, [(ana, ana_booking)] = _full_session(engine, now + timedelta(days=2))
    carla, bruno = _student(engine, credits=0), _student(engine, credits=1)
    entry_carla = add_waiting(engine, carla, session, now - timedelta(hours=2))
    entry_bruno = add_waiting(engine, bruno, session, now - timedelta(hours=1))

    assert _cancel(engine, ana, ana_booking, now).ok

    carla_entry = _entry(engine, entry_carla)
    assert carla_entry.status == "removed"
    assert carla_entry.reason == "no credits"
    assert len(_notifications(engine, carla)) == 1
    assert not _booked(engine, carla, session)
    assert _booked(engine, bruno, session)
    assert _entry(engine, entry_bruno).status == "promoted"
    assert _balance(engine, bruno) == 0


def test_r4_3_clashing_first_in_line_removed_and_next_tried(engine, now):
    start = now + timedelta(days=2)
    session, [(ana, ana_booking)] = _full_session(engine, start)
    clasher, next_up = _student(engine, credits=2), _student(engine, credits=1)
    other = make_session(engine, make_member(engine, role="instructor"), start)
    make_booking(engine, clasher, other)
    entry_clasher = add_waiting(engine, clasher, session, now - timedelta(hours=2))
    entry_next = add_waiting(engine, next_up, session, now - timedelta(hours=1))

    assert _cancel(engine, ana, ana_booking, now).ok

    clasher_entry = _entry(engine, entry_clasher)
    assert clasher_entry.status == "removed"
    assert clasher_entry.reason == "clash"
    assert len(_notifications(engine, clasher)) == 1
    assert _balance(engine, clasher) == 1
    assert _booked(engine, next_up, session)
    assert _entry(engine, entry_next).status == "promoted"


def test_r4_4_cancel_at_start_minus_1_59_promotes_nobody(engine, now):
    session, [(ana, ana_booking)] = _full_session(
        engine, now + timedelta(hours=1, minutes=59)
    )
    bruno = _student(engine, credits=1)
    entry = add_waiting(engine, bruno, session, now - timedelta(hours=1))

    assert _cancel(engine, ana, ana_booking, now).ok

    assert _entry(engine, entry).status == "waiting"
    assert not _booked(engine, bruno, session)
    assert _balance(engine, bruno) == 1
    assert _notifications(engine, bruno) == []
    assert _booked_count(engine, session) == 0


# --- Scenario A6 (R4.3, R5.2) ---

def test_a6_cancel_30h_before_full_session_refunds_ana_removes_carla_books_bruno(engine, now):
    session, [(ana, ana_booking)] = _full_session(engine, now + timedelta(hours=30))
    carla, bruno = _student(engine, credits=0), _student(engine, credits=1)
    entry_carla = add_waiting(engine, carla, session, now - timedelta(hours=2))
    entry_bruno = add_waiting(engine, bruno, session, now - timedelta(hours=1))

    result = _cancel(engine, ana, ana_booking, now)

    assert result.ok, result.message
    assert result.data["refunded"] is True
    assert _balance(engine, ana) == 1
    assert _entry(engine, entry_carla).status == "removed"
    assert _entry(engine, entry_carla).reason == "no credits"
    assert len(_notifications(engine, carla)) == 1
    assert _booked(engine, bruno, session)
    assert _balance(engine, bruno) == 0
    assert _entry(engine, entry_bruno).status == "promoted"
    [note] = _notifications(engine, bruno)
    assert note.message.startswith("You got a place")
    assert _booked_count(engine, session) == 1


# --- Capacity increase (R2.10) ---

def test_r2_10_raising_capacity_by_2_promotes_first_two_eligible(engine, now):
    from lineup.services.booking import promote_waitlist

    session, _ = _full_session(engine, now + timedelta(days=2))
    first, broke, second, third = (
        _student(engine, credits=1), _student(engine, credits=0),
        _student(engine, credits=1), _student(engine, credits=1),
    )
    add_waiting(engine, first, session, now - timedelta(hours=4))
    entry_broke = add_waiting(engine, broke, session, now - timedelta(hours=3))
    add_waiting(engine, second, session, now - timedelta(hours=2))
    entry_third = add_waiting(engine, third, session, now - timedelta(hours=1))
    s = schema.surf_sessions

    with engine.begin() as conn:
        conn.execute(update(s).where(s.c.id == session).values(capacity=s.c.capacity + 2))
        promoted = promote_waitlist(conn, session, now)

    assert promoted == [first, second]
    assert _booked_count(engine, session) == 3
    assert _entry(engine, entry_broke).status == "removed"
    assert _entry(engine, entry_third).status == "waiting"
