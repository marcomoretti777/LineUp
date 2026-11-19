"""Load the demo data of spec section 14 into a local or live database.

Running it twice gives the same result: everything but the members is
wiped and rebuilt, while members are matched by address so an account
created through the login flow keeps its auth_user_id.

Rules: section 14, R6, R10.1.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine

from lineup import db, schema
from lineup.config import CREDIT_PACKS, DEFAULT_THRESHOLDS
from lineup.models import Level, Role
from lineup.timeutil import utcnow

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


def seed(engine: Engine, now: datetime | None = None) -> None:
    """Reset the demo data and load spec section 14, in one transaction.

    Rules: section 14, R6, R10.1.
    """
    now = now or utcnow()
    with engine.begin() as conn:
        _reset(conn)
        _upsert_members(conn)
        _upsert_catalogue(conn)
