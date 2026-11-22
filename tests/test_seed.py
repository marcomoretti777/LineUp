"""The demo seed of spec section 14: members, sessions, credits, idempotence.

The seed is pure local work: it never reaches Supabase or the network. These
tests run it against the in-memory engine from tests/conftest.py.
"""

from datetime import timedelta

import pytest
from sqlalchemy import insert, select

from lineup import db, schema
from lineup.models import Attendance, BookingStatus, Level, RequestStatus, Role, WaitStatus
from lineup.timeutil import from_local, local_date
from scripts.seed import SEED_MEMBERS, seed
from tests.conftest import make_member


def members_by_email(engine):
    """Every seeded member keyed by address."""
    with engine.begin() as conn:
        rows = conn.execute(
            select(schema.members.c.id, schema.members.c.email,
                   schema.members.c.full_name, schema.members.c.role,
                   schema.members.c.level, schema.members.c.auth_user_id)
        ).all()
    return {row.email: row for row in rows}


def session_at(engine, start):
    """The session starting at a naive UTC moment, or None."""
    with engine.begin() as conn:
        return conn.execute(
            select(schema.surf_sessions).where(schema.surf_sessions.c.starts_at == start)
        ).one_or_none()


def booked_emails(engine, session_id):
    """Addresses with a confirmed booking in a session, sorted."""
    with engine.begin() as conn:
        rows = conn.execute(
            select(schema.members.c.email)
            .select_from(schema.bookings.join(
                schema.members, schema.members.c.id == schema.bookings.c.member_id))
            .where(schema.bookings.c.session_id == session_id)
            .where(schema.bookings.c.status == BookingStatus.CONFIRMED.value)
        ).scalars().all()
    return sorted(rows)


def start_of(now, days, hour, minute=0):
    """A naive UTC start built from the local date of `now` plus `days`."""
    from datetime import time

    return from_local(local_date(now) + timedelta(days=days), time(hour, minute))


# --- idempotence and invariants --------------------------------------------

def test_seed_runs_twice_and_leaves_the_data_healthy(engine, now):
    seed(engine, now)
    with engine.begin() as conn:
        assert db.check_invariants(conn) == []
    seed(engine, now)
    with engine.begin() as conn:
        assert db.check_invariants(conn) == []


def test_seed_twice_gives_the_same_counts(engine, now):
    seed(engine, now)
    first = members_by_email(engine)
    seed(engine, now)
    assert set(members_by_email(engine)) == set(first)


# --- the seven demo accounts of section 14 ---------------------------------

def test_section_14_seeds_exactly_the_seven_demo_accounts(engine, now):
    seed(engine, now)
    people = members_by_email(engine)
    assert len(people) == 7
    assert set(people) == {m["email"] for m in SEED_MEMBERS}


@pytest.mark.parametrize("email,name,role", [
    ("lineup.admin@novasbe.pt", "Marta Silva", Role.ADMIN),
    ("lineup.tiago@novasbe.pt", "Tiago Costa", Role.INSTRUCTOR),
    ("lineup.ines@novasbe.pt", "Inês Rocha", Role.INSTRUCTOR),
    ("lineup.ana@novasbe.pt", "Ana Martins", Role.STUDENT),
    ("lineup.bruno@novasbe.pt", "Bruno Lopes", Role.STUDENT),
    ("lineup.carla@novasbe.pt", "Carla Dias", Role.STUDENT),
    ("lineup.diogo@novasbe.pt", "Diogo Alves", Role.STUDENT),
])
def test_section_14_demo_account_has_its_name_and_role(engine, now, email, name, role):
    seed(engine, now)
    person = members_by_email(engine)[email]
    assert person.full_name == name
    assert person.role == role


@pytest.mark.parametrize("email,level", [
    ("lineup.ana@novasbe.pt", Level.BEGINNER),
    ("lineup.bruno@novasbe.pt", Level.INTERMEDIATE),
    ("lineup.carla@novasbe.pt", Level.INTERMEDIATE),
    ("lineup.diogo@novasbe.pt", Level.INTERMEDIATE),
])
def test_section_14_student_levels(engine, now, email, level):
    seed(engine, now)
    assert members_by_email(engine)[email].level == level


# --- balances and the credit history ---------------------------------------

@pytest.mark.parametrize("email,balance", [
    ("lineup.ana@novasbe.pt", 3),
    ("lineup.bruno@novasbe.pt", 2),
    ("lineup.carla@novasbe.pt", 0),
    ("lineup.diogo@novasbe.pt", 2),
])
def test_section_14_balance_after_seeding(engine, now, email, balance):
    seed(engine, now)
    member_id = members_by_email(engine)[email].id
    with engine.begin() as conn:
        assert db.ledger_balance(conn, member_id) == balance


def test_diogo_has_exactly_one_pending_five_pack_request(engine, now):
    seed(engine, now)
    diogo = members_by_email(engine)["lineup.diogo@novasbe.pt"].id
    with engine.begin() as conn:
        rows = conn.execute(
            select(schema.credit_packs.c.credits)
            .select_from(schema.credit_requests.join(
                schema.credit_packs,
                schema.credit_packs.c.id == schema.credit_requests.c.pack_id))
            .where(schema.credit_requests.c.member_id == diogo)
            .where(schema.credit_requests.c.status == RequestStatus.PENDING.value)
        ).scalars().all()
    assert rows == [5]


def test_the_catalogue_holds_the_three_packs_and_both_thresholds(engine, now):
    seed(engine, now)
    with engine.begin() as conn:
        packs = conn.execute(select(schema.credit_packs.c.credits)).scalars().all()
        levels = conn.execute(select(schema.condition_thresholds.c.level)).scalars().all()
    assert sorted(packs) == [1, 5, 10]
    assert sorted(levels) == [Level.BEGINNER, Level.INTERMEDIATE]


# --- the sessions of section 14 --------------------------------------------

def test_tomorrow_ten_is_a_beginner_session_with_ana_and_bruno(engine, now):
    seed(engine, now)
    found = session_at(engine, start_of(now, 1, 10))
    assert found is not None
    assert found.level == Level.BEGINNER
    assert found.capacity == 4
    assert found.booked_count == 2
    assert booked_emails(engine, found.id) == [
        "lineup.ana@novasbe.pt", "lineup.bruno@novasbe.pt"
    ]


def test_tomorrow_ten_thirty_is_an_empty_session_for_the_clash_demo(engine, now):
    seed(engine, now)
    found = session_at(engine, start_of(now, 1, 10, 30))
    assert found is not None
    assert found.booked_count == 0
    ten = session_at(engine, start_of(now, 1, 10))
    assert found.instructor_id != ten.instructor_id


def test_in_two_days_the_last_place_session_has_one_of_two_taken(engine, now):
    seed(engine, now)
    found = session_at(engine, start_of(now, 2, 10))
    assert found is not None
    assert found.capacity == 2
    assert found.booked_count == 1
    assert booked_emails(engine, found.id) == ["lineup.diogo@novasbe.pt"]


def test_in_three_days_the_intermediate_session_is_full_with_bruno_waiting(engine, now):
    seed(engine, now)
    found = session_at(engine, start_of(now, 3, 14))
    assert found is not None
    assert found.level == Level.INTERMEDIATE
    assert found.capacity == 2
    assert found.booked_count == 2
    assert booked_emails(engine, found.id) == [
        "lineup.carla@novasbe.pt", "lineup.diogo@novasbe.pt"
    ]
    bruno = members_by_email(engine)["lineup.bruno@novasbe.pt"].id
    with engine.begin() as conn:
        waiting = conn.execute(
            select(schema.waitlist_entries.c.member_id)
            .where(schema.waitlist_entries.c.session_id == found.id)
            .where(schema.waitlist_entries.c.status == WaitStatus.WAITING.value)
        ).scalars().all()
    assert waiting == [bruno]


def test_in_nine_days_a_beginner_session_sits_beyond_the_forecast(engine, now):
    seed(engine, now)
    found = session_at(engine, start_of(now, 9, 10))
    assert found is not None
    assert found.level == Level.BEGINNER


def test_the_two_past_sessions_carry_the_attendance_of_section_14(engine, now):
    seed(engine, now)
    people = members_by_email(engine)

    two_weeks = session_at(engine, start_of(now, -14, 10))
    one_week = session_at(engine, start_of(now, -7, 10))
    assert two_weeks is not None and one_week is not None

    with engine.begin() as conn:
        older = dict(conn.execute(
            select(schema.bookings.c.member_id, schema.bookings.c.attendance)
            .where(schema.bookings.c.session_id == two_weeks.id)
        ).all())
        newer = dict(conn.execute(
            select(schema.bookings.c.member_id, schema.bookings.c.attendance)
            .where(schema.bookings.c.session_id == one_week.id)
        ).all())

    assert older[people["lineup.ana@novasbe.pt"].id] == Attendance.ATTENDED
    assert older[people["lineup.bruno@novasbe.pt"].id] == Attendance.ATTENDED
    assert newer[people["lineup.bruno@novasbe.pt"].id] == Attendance.ATTENDED
    assert newer[people["lineup.diogo@novasbe.pt"].id] == Attendance.NO_SHOW


def test_students_have_read_and_unread_notifications(engine, now):
    seed(engine, now)
    ana = members_by_email(engine)["lineup.ana@novasbe.pt"].id
    with engine.begin() as conn:
        total = conn.execute(
            select(schema.notifications.c.id)
            .where(schema.notifications.c.member_id == ana)
        ).scalars().all()
        unread = db.unread_count(conn, ana)
    assert len(total) >= 2
    assert 0 < unread < len(total)


# --- the two linking rules the live database depends on --------------------

def test_an_existing_seeded_email_keeps_its_auth_id_and_takes_the_seeded_role(engine, now):
    with engine.begin() as conn:
        existing = conn.execute(
            insert(schema.members).values(
                auth_user_id="auth-ana-live",
                email="lineup.ana@novasbe.pt",
                full_name="Ana From Login",
                role=Role.STUDENT.value,
                level=Level.INTERMEDIATE.value,
            )
        ).inserted_primary_key[0]

    seed(engine, now)

    ana = members_by_email(engine)["lineup.ana@novasbe.pt"]
    assert ana.id == existing
    assert ana.auth_user_id == "auth-ana-live"
    assert ana.full_name == "Ana Martins"
    assert ana.level == Level.BEGINNER


def test_a_member_with_an_auth_id_outside_the_seed_list_survives_a_reset(engine, now):
    with engine.begin() as conn:
        kept = conn.execute(
            insert(schema.members).values(
                auth_user_id="auth-test1",
                email="lineup.test1@novasbe.pt",
                full_name="Test One",
                role=Role.STUDENT.value,
                level=Level.BEGINNER.value,
            )
        ).inserted_primary_key[0]

    seed(engine, now)

    people = members_by_email(engine)
    assert "lineup.test1@novasbe.pt" in people
    assert people["lineup.test1@novasbe.pt"].id == kept


def test_a_member_without_an_auth_id_outside_the_seed_list_is_removed(engine, now):
    make_member(engine, role="admin", name="Rita Admin", email="rita@novasbe.pt")
    seed(engine, now)
    assert "rita@novasbe.pt" not in members_by_email(engine)
