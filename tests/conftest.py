"""Shared fixtures and factories for every lane's tests.

lineup.db and lineup.schema are imported inside the functions, so a test
file that does not use the database collects even if storage is broken.
Factories write straight to the tables and keep every invariant of spec
section 9, except that make_booking needs credits given first.
"""

import itertools
from datetime import datetime

import pytest

_numbers = itertools.count(1)


@pytest.fixture
def engine():
    """A fresh in-memory SQLite database with all tables and defaults."""
    from lineup import db

    eng = db.make_engine("sqlite://")
    db.init_db(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def now():
    """Fri 20 Nov 2026, 09:00 UTC; Lisbon equals UTC in November."""
    return datetime(2026, 11, 20, 9, 0)


@pytest.fixture(autouse=True)
def _check_invariants_after_test(request):
    """Fail any test that used `engine` and left broken data behind.

    The engine is requested here, before the test runs, so it is torn
    down after this check rather than before it.
    """
    if "engine" not in request.fixturenames:
        yield
        return
    eng = request.getfixturevalue("engine")
    yield
    from lineup import db

    with eng.connect() as conn:
        problems = db.check_invariants(conn)
    if problems:
        pytest.fail("Broken invariants:\n" + "\n".join(problems))


def make_member(engine, role="student", level="beginner", name=None, email=None):
    """Insert a member and return its id."""
    from sqlalchemy import insert

    from lineup import schema

    n = next(_numbers)
    values = {
        "email": (email or f"member{n}@novasbe.pt").strip().lower(),
        "full_name": name or f"Member {n}",
        "role": role,
        "level": level,
    }
    with engine.begin() as conn:
        return conn.execute(insert(schema.members).values(**values)).inserted_primary_key[0]


def make_session(engine, instructor_id, start, duration_min=90, capacity=4,
                 level="beginner", status="scheduled"):
    """Insert a surf session starting at `start` (naive UTC) and return its id."""
    from sqlalchemy import insert

    from lineup import schema

    values = {
        "instructor_id": instructor_id,
        "starts_at": start,
        "duration_min": duration_min,
        "level": level,
        "capacity": capacity,
        "booked_count": 0,
        "status": status,
    }
    with engine.begin() as conn:
        return conn.execute(insert(schema.surf_sessions).values(**values)).inserted_primary_key[0]


def give_credits(engine, member_id, n):
    """Add n credits to a member through a purchase ledger row."""
    from lineup import db

    with engine.begin() as conn:
        db.ledger_add(conn, member_id, n, "purchase", f"purchase:test-{next(_numbers)}")


def make_booking(engine, member_id, session_id):
    """Book a place, charging 1 credit, and return the booking id.

    Give the member credits first, or the negative-balance invariant fails.
    """
    from sqlalchemy import insert, update

    from lineup import db, schema

    with engine.begin() as conn:
        booking_id = conn.execute(
            insert(schema.bookings).values(
                session_id=session_id, member_id=member_id, status="confirmed"
            )
        ).inserted_primary_key[0]
        conn.execute(
            update(schema.surf_sessions)
            .where(schema.surf_sessions.c.id == session_id)
            .values(booked_count=schema.surf_sessions.c.booked_count + 1)
        )
        db.ledger_add(conn, member_id, -1, "booking", f"booking:{booking_id}")
    return booking_id


def add_waiting(engine, member_id, session_id, joined_at):
    """Put a member on a session's waitlist at `joined_at` and return the entry id."""
    from sqlalchemy import insert

    from lineup import schema

    with engine.begin() as conn:
        return conn.execute(
            insert(schema.waitlist_entries).values(
                session_id=session_id, member_id=member_id, status="waiting",
                created_at=joined_at, updated_at=joined_at,
            )
        ).inserted_primary_key[0]
