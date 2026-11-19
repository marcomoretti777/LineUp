"""Load the demo data of spec section 14 into a local or live database.

Running it twice gives the same result: everything but the members is
wiped and rebuilt, while members are matched by address so an account
created through the login flow keeps its auth_user_id.

Rules: section 14, R6, R10.1.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine

from lineup import db, schema
from lineup.config import CREDIT_PACKS, DEFAULT_THRESHOLDS
from lineup.models import Attendance, BookingStatus, Level, Role, WaitStatus
from lineup.timeutil import from_local, local_date, utcnow

# The seven demo accounts of spec section 14. The address is the key: the
# live database already holds rows created by the login flow, and they must
# be updated, never duplicated.
SEED_MEMBERS = [
    {"email": "lineup.admin@novasbe.pt", "full_name": "Marta Silva",
     "role": Role.ADMIN, "level": Level.BEGINNER},
    {"email": "lineup.tiago@novasbe.pt", "full_name": "Tiago Costa",
     "role": Role.INSTRUCTOR, "level": Level.INTERMEDIATE},
    {"email": "lineup.ines@novasbe.pt", "full_name": "Inês Rocha",
     "role": Role.INSTRUCTOR, "level": Level.INTERMEDIATE},
    {"email": "lineup.ana@novasbe.pt", "full_name": "Ana Martins",
     "role": Role.STUDENT, "level": Level.BEGINNER},
    {"email": "lineup.bruno@novasbe.pt", "full_name": "Bruno Lopes",
     "role": Role.STUDENT, "level": Level.INTERMEDIATE},
    {"email": "lineup.carla@novasbe.pt", "full_name": "Carla Dias",
     "role": Role.STUDENT, "level": Level.INTERMEDIATE},
    {"email": "lineup.diogo@novasbe.pt", "full_name": "Diogo Alves",
     "role": Role.STUDENT, "level": Level.INTERMEDIATE},
]

SEED_EMAILS = [person["email"] for person in SEED_MEMBERS]

ADMIN = "lineup.admin@novasbe.pt"
TIAGO = "lineup.tiago@novasbe.pt"
INES = "lineup.ines@novasbe.pt"
ANA = "lineup.ana@novasbe.pt"
BRUNO = "lineup.bruno@novasbe.pt"
CARLA = "lineup.carla@novasbe.pt"
DIOGO = "lineup.diogo@novasbe.pt"

# (days from today, start, instructor, level, capacity, duration).
# Dates are relative, so the demo always has upcoming sessions.
SEED_SESSIONS = [
    ("past_two_weeks", -14, time(10, 0), TIAGO, Level.BEGINNER, 4, 90),
    ("past_one_week", -7, time(10, 0), TIAGO, Level.BEGINNER, 4, 90),
    ("tomorrow_ten", 1, time(10, 0), TIAGO, Level.BEGINNER, 4, 90),
    ("tomorrow_ten_thirty", 1, time(10, 30), INES, Level.BEGINNER, 4, 90),
    ("last_place", 2, time(10, 0), TIAGO, Level.BEGINNER, 2, 90),
    ("intermediate_full", 3, time(14, 0), INES, Level.INTERMEDIATE, 2, 90),
    ("beyond_forecast", 9, time(10, 0), TIAGO, Level.BEGINNER, 4, 90),
]

# (session key, member, attendance) for every confirmed booking.
SEED_BOOKINGS = [
    ("past_two_weeks", ANA, Attendance.ATTENDED),
    ("past_two_weeks", BRUNO, Attendance.ATTENDED),
    ("past_one_week", BRUNO, Attendance.ATTENDED),
    ("past_one_week", DIOGO, Attendance.NO_SHOW),
    ("tomorrow_ten", ANA, None),
    ("tomorrow_ten", BRUNO, None),
    ("last_place", DIOGO, None),
    ("intermediate_full", CARLA, None),
    ("intermediate_full", DIOGO, None),
]

# Bruno waits for the full Intermediate session (R4.1).
SEED_WAITING = [("intermediate_full", BRUNO)]


def _reset(conn) -> None:
    """Delete the demo data in dependency order, sparing linked accounts.

    A member holding an auth_user_id is never deleted, because a Supabase
    account would otherwise be left pointing at nothing. Two foreign keys
    into members are cleared first, or the member delete fails.

    Rules: section 14.
    """
    for table in (schema.notifications, schema.credit_ledger,
                  schema.credit_requests, schema.waitlist_entries,
                  schema.bookings, schema.surf_sessions):
        conn.execute(delete(table))

    conn.execute(update(schema.condition_thresholds).values(
        updated_by=None, updated_at=None))

    conn.execute(
        delete(schema.members)
        .where(schema.members.c.auth_user_id.is_(None))
        .where(schema.members.c.email.not_in(SEED_EMAILS))
    )


def _upsert_members(conn) -> dict[str, int]:
    """Create or refresh the seven demo accounts; return their ids by address.

    An existing address keeps its id and auth_user_id and takes the seeded
    name, role and level, so the live rows F06 created are reused.

    Rules: section 14, R1.4.
    """
    existing = dict(conn.execute(
        select(schema.members.c.email, schema.members.c.id)
    ).all())

    ids: dict[str, int] = {}
    for person in SEED_MEMBERS:
        values = {
            "full_name": person["full_name"],
            "role": person["role"].value,
            "level": person["level"].value,
        }
        member_id = existing.get(person["email"])
        if member_id is None:
            ids[person["email"]] = conn.execute(
                insert(schema.members).values(email=person["email"], **values)
            ).inserted_primary_key[0]
        else:
            conn.execute(
                update(schema.members)
                .where(schema.members.c.id == member_id)
                .values(**values)
            )
            ids[person["email"]] = member_id
    return ids


def _upsert_catalogue(conn) -> dict[int, int]:
    """Make sure the three packs and both thresholds exist; return pack ids.

    Rules: R10.1, R6.
    """
    packs = dict(conn.execute(
        select(schema.credit_packs.c.credits, schema.credit_packs.c.id)
    ).all())
    for name, credits, price_cents in CREDIT_PACKS:
        if credits in packs:
            conn.execute(
                update(schema.credit_packs)
                .where(schema.credit_packs.c.id == packs[credits])
                .values(name=name, price_cents=price_cents, active=True)
            )
        else:
            packs[credits] = conn.execute(
                insert(schema.credit_packs).values(
                    name=name, credits=credits, price_cents=price_cents)
            ).inserted_primary_key[0]

    known = set(conn.execute(select(schema.condition_thresholds.c.level)).scalars())
    for level, (go_wave, go_wind, marginal_wave, marginal_wind) in DEFAULT_THRESHOLDS.items():
        values = {
            "go_wave_m": go_wave, "go_wind_kmh": go_wind,
            "marginal_wave_m": marginal_wave, "marginal_wind_kmh": marginal_wind,
        }
        if level in known:
            conn.execute(
                update(schema.condition_thresholds)
                .where(schema.condition_thresholds.c.level == level)
                .values(**values)
            )
        else:
            conn.execute(
                insert(schema.condition_thresholds).values(level=level, **values)
            )
    return packs


def _insert_sessions(conn, people: dict[str, int], now: datetime) -> dict[str, int]:
    """Insert the sessions of section 14 around the local date of `now`.

    Rules: section 14, R2.
    """
    today = local_date(now)
    ids: dict[str, int] = {}
    for key, days, clock, instructor, level, capacity, duration in SEED_SESSIONS:
        ids[key] = conn.execute(
            insert(schema.surf_sessions).values(
                instructor_id=people[instructor],
                starts_at=from_local(today + timedelta(days=days), clock),
                duration_min=duration,
                level=level.value,
                capacity=capacity,
                booked_count=0,
            )
        ).inserted_primary_key[0]
    return ids


def _insert_bookings(conn, people: dict[str, int], sessions: dict[str, int]) -> list[tuple[int, str]]:
    """Insert the confirmed bookings and the waiting entry; return them.

    booked_count is set from the rows actually written, which is what
    invariant 1 of section 9 compares against.

    Rules: section 14, R3.1, R4.1.
    """
    written: list[tuple[int, str]] = []
    taken: dict[str, int] = {}
    for key, email, attendance in SEED_BOOKINGS:
        booking_id = conn.execute(
            insert(schema.bookings).values(
                session_id=sessions[key],
                member_id=people[email],
                status=BookingStatus.CONFIRMED.value,
                attendance=attendance.value if attendance else None,
            )
        ).inserted_primary_key[0]
        written.append((booking_id, email))
        taken[key] = taken.get(key, 0) + 1

    for key, count in taken.items():
        conn.execute(
            update(schema.surf_sessions)
            .where(schema.surf_sessions.c.id == sessions[key])
            .values(booked_count=count)
        )

    for key, email in SEED_WAITING:
        conn.execute(
            insert(schema.waitlist_entries).values(
                session_id=sessions[key],
                member_id=people[email],
                status=WaitStatus.WAITING.value,
            )
        )
    return written


def seed(engine: Engine, now: datetime | None = None) -> None:
    """Reset the demo data and load spec section 14, in one transaction.

    Rules: section 14, R6, R10.1.
    """
    now = now or utcnow()
    with engine.begin() as conn:
        _reset(conn)
        people = _upsert_members(conn)
        _upsert_catalogue(conn)
        sessions = _insert_sessions(conn, people, now)
        _insert_bookings(conn, people, sessions)
