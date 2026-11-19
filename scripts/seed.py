"""Load the demo data of spec section 14 into a local or live database.

Running it twice gives the same result: everything but the members is
wiped and rebuilt, while members are matched by address so an account
created through the login flow keeps its auth_user_id.

Rules: section 14, R6, R10.1.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

# Running "uv run python scripts/seed.py" puts scripts/ on sys.path, not the
# repository root, so lineup would not import. Added before the imports below.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, insert, select, update  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from lineup import config, db, schema  # noqa: E402
from lineup.config import CREDIT_PACKS, DEFAULT_THRESHOLDS  # noqa: E402
from lineup.models import (Attendance, BookingStatus, LedgerKind, Level,  # noqa: E402
                           RequestStatus, Role, WaitStatus)
from lineup.timeutil import from_local, local_date, utcnow  # noqa: E402

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

# Packs approved last month, in credits. Minus one credit per booking
# these give the balances section 14 states: Ana 3, Bruno 2, Carla 0,
# Diogo 2.
SEED_PURCHASES = [(ANA, 5), (BRUNO, 5), (CARLA, 1), (DIOGO, 5)]

# (member, kind, message, read) for the Inbox and the sidebar count.
SEED_NOTIFICATIONS = [
    (ANA, "booking", "Booked: tomorrow at 10:00.", True),
    (ANA, "credits", "Your 5-session pack was approved.", False),
    (BRUNO, "waitlist", "You are waiting for the Intermediate session.", False),
    (BRUNO, "credits", "Your 5-session pack was approved.", True),
    (CARLA, "booking", "Booked: the Intermediate session.", False),
    (DIOGO, "attendance", "You were marked as a no-show.", True),
    (DIOGO, "credits", "Your 5-session pack request is pending.", False),
]


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


def _insert_credits(conn, people: dict[str, int], packs: dict[int, int],
                    bookings: list[tuple[int, str]], now: datetime) -> None:
    """Write the purchases, the booking charges and Diogo's pending request.

    Every charge carries the ref booking:<id>, because invariant 4 of
    section 9 expects exactly one such row per booking. Purchases use their
    own refs, so a second run cannot double them.

    Rules: section 14, R10.1, R10.7, R10.8.
    """
    last_month = now - timedelta(days=30)
    admin = people[ADMIN]

    for email, credits in SEED_PURCHASES:
        pack_id = packs[credits]
        request_id = conn.execute(
            insert(schema.credit_requests).values(
                member_id=people[email],
                pack_id=pack_id,
                payment_ref=f"DEMO-{email.split('@')[0].split('.')[-1].upper()}",
                status=RequestStatus.APPROVED.value,
                decided_by=admin,
                decided_at=last_month,
                created_at=last_month,
            )
        ).inserted_primary_key[0]
        db.ledger_add(conn, people[email], credits, LedgerKind.PURCHASE,
                      f"request:{request_id}", f"{credits}-session pack")

    for booking_id, email in bookings:
        db.ledger_add(conn, people[email], -1, LedgerKind.BOOKING,
                      f"booking:{booking_id}")

    # R10.2 allows this alongside his approved pack: only one may be pending.
    conn.execute(
        insert(schema.credit_requests).values(
            member_id=people[DIOGO],
            pack_id=packs[5],
            payment_ref="DEMO-DIOGO-2",
            status=RequestStatus.PENDING.value,
            created_at=now - timedelta(days=1),
        )
    )

    for email, kind, message, was_read in SEED_NOTIFICATIONS:
        conn.execute(
            insert(schema.notifications).values(
                member_id=people[email],
                kind=kind,
                message=message,
                created_at=now - timedelta(days=1),
                read_at=now - timedelta(hours=12) if was_read else None,
            )
        )


def seed(engine: Engine, now: datetime | None = None) -> None:
    """Reset the demo data and load spec section 14, in one transaction.

    Rules: section 14, R6, R10.1.
    """
    now = now or utcnow()
    with engine.begin() as conn:
        _reset(conn)
        people = _upsert_members(conn)
        packs = _upsert_catalogue(conn)
        sessions = _insert_sessions(conn, people, now)
        bookings = _insert_bookings(conn, people, sessions)
        _insert_credits(conn, people, packs, bookings, now)


def _live_engine() -> Engine:
    """Build the engine for the deployed database, or refuse without a URL.

    The URL holds the database password, so it is read only through
    config.get_secret and never printed or logged.

    Rules: section 12 (secrets), section 14.
    """
    url = config.get_secret("DATABASE_URL")
    if not url:
        raise SystemExit(
            "DATABASE_URL is not set. Put it in .streamlit/secrets.toml or the "
            "environment before seeding the live database."
        )
    return db.make_engine(url)


def main(argv: list[str] | None = None) -> int:
    """Seed the local file database, or the live one behind a typed RESET.

    Rules: section 14, section 12.
    """
    parser = argparse.ArgumentParser(description="Load the LineUp demo data.")
    parser.add_argument(
        "--target", choices=("local", "live"), default="local",
        help="local writes data/lineup.db (the default); live uses DATABASE_URL",
    )
    args = parser.parse_args(argv)

    if args.target == "live":
        # Named, never shown: printing the URL would leak the password.
        print("This resets the LIVE LineUp database and deletes its demo data.")
        if input("Type RESET to continue: ").strip() != "RESET":
            print("Nothing was changed.")
            return 1
        engine = _live_engine()
    else:
        engine = db.make_engine()

    db.init_db(engine)
    seed(engine)
    print(f"Seeded the {args.target} database with the demo data of section 14.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
