"""Member actions: first-login profiles, roles and levels. Owner: the lead.

Follows the service pattern in docs/contract.md: load the actor, check the
permission, apply the rule, write and notify in one transaction, return a
Result.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine

from lineup import db, schema
from lineup.logic.accounts import normalise_email, normalise_name, validate_name
from lineup.models import Code, Level, Result, Role, fill
from lineup.permissions import Action, require
from lineup.timeutil import utcnow

_LOG = logging.getLogger(__name__)

def _fallback_name(email: str) -> str:
    """Build a usable display name from an address when none was given.

    Rules: R1.2, R1.4.
    """
    local = email.partition("@")[0].replace(".", " ").replace("-", " ")
    name = normalise_name(local).title()
    return name if validate_name(name) is None else "New Member"


def login_member(engine: Engine, auth_user_id: str, email: str,
                 full_name: str | None = None) -> Result:
    """Return the member for an auth account, linking or creating the profile.

    No permission check, by design: this runs before an actor exists and is
    what creates one. A seeded address keeps the role and level it was
    seeded with, so logging in never demotes an admin. A profile whose
    Supabase account was deleted and re-created is re-linked, keeping its
    role, level, credits and history.

    Rules: R1.4.
    """
    address = normalise_email(email)
    name = normalise_name(full_name) if full_name else ""
    if validate_name(name) is not None:
        name = _fallback_name(address)

    with engine.begin() as conn:
        known = conn.execute(
            select(schema.members.c.id)
            .where(schema.members.c.auth_user_id == auth_user_id)
        ).scalar_one_or_none()
        if known is not None:
            return Result.success("Signed in.", known)

        # A profile with this address but no auth id was seeded; one with a
        # different auth id lost its Supabase account (deleted in the
        # dashboard) and this is its owner signing up again. Supabase allows
        # one account per address, so in both cases the profile follows the
        # new auth id instead of a duplicate being inserted.
        existing = conn.execute(
            select(schema.members.c.id, schema.members.c.auth_user_id)
            .where(schema.members.c.email == address)
        ).first()
        if existing is not None:
            if existing.auth_user_id is not None:
                _LOG.warning("Member %s re-linked to a re-created Supabase account",
                             existing.id)
            conn.execute(
                update(schema.members)
                .where(schema.members.c.id == existing.id)
                .values(auth_user_id=auth_user_id)
            )
            return Result.success("Signed in.", existing.id)

        member_id = conn.execute(
            insert(schema.members).values(
                auth_user_id=auth_user_id,
                email=address,
                full_name=name,
                role=Role.STUDENT.value,
                level=Level.BEGINNER.value,
            )
        ).inserted_primary_key[0]
        return Result.success("Welcome to LineUp.", member_id)


def _only_admin_left(conn, member_id: int) -> bool:
    """Say whether this member is the single remaining admin.

    Rules: R1.6.
    """
    admins = conn.execute(
        select(schema.members.c.id).where(schema.members.c.role == Role.ADMIN.value)
    ).scalars().all()
    return admins == [member_id]


def change_role(engine: Engine, actor_id: int, member_id: int, role: str,
                now: datetime | None = None) -> Result:
    """Give a member another role, never leaving the club without an admin.

    Rules: R1.5, R1.6, section 3.
    """
    now = now or utcnow()
    try:
        new_role = Role(role)
    except ValueError:
        return Result.fail(
            Code.INVALID,
            fill(Code.INVALID, field="Role", problem="that is not a role",
                 allowed=", ".join(r.value for r in Role)),
        )

    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
        denied = require(actor, Action.MANAGE_MEMBERS)
        if denied:
            return denied

        target = db.get_actor(conn, member_id)
        if target is None:
            return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
        if target.role == new_role:
            return Result.fail(Code.ALREADY_DONE, fill(Code.ALREADY_DONE))
        if new_role != Role.ADMIN and _only_admin_left(conn, member_id):
            return Result.fail(
                Code.INVALID,
                fill(Code.INVALID, field="Role",
                     problem="the club would be left without an admin",
                     allowed="promote another admin first"),
            )

        conn.execute(
            update(schema.members)
            .where(schema.members.c.id == member_id)
            .values(role=new_role.value)
        )
        db.notify(conn, member_id, "role_changed",
                  f"Your role is now {new_role.value}.")
        return Result.success(
            f"{target.full_name} is now {new_role.value}.", member_id
        )


def change_level(engine: Engine, actor_id: int, member_id: int, level: str,
                 now: datetime | None = None) -> Result:
    """Give a member another surfing level.

    Rules: R1.5, section 3.
    """
    now = now or utcnow()
    try:
        new_level = Level(level)
    except ValueError:
        return Result.fail(
            Code.INVALID,
            fill(Code.INVALID, field="Level", problem="that is not a level",
                 allowed=", ".join(l.value for l in Level)),
        )

    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
        denied = require(actor, Action.MANAGE_MEMBERS)
        if denied:
            return denied

        target = db.get_actor(conn, member_id)
        if target is None:
            return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
        if target.level == new_level:
            return Result.fail(Code.ALREADY_DONE, fill(Code.ALREADY_DONE))

        conn.execute(
            update(schema.members)
            .where(schema.members.c.id == member_id)
            .values(level=new_level.value)
        )
        db.notify(conn, member_id, "level_changed",
                  f"Your level is now {new_level.value}.")
        return Result.success(
            f"{target.full_name} is now {new_level.value}.", member_id
        )


def list_members(engine: Engine, actor_id: int, search: str | None = None) -> Result:
    """List members with role, level and balance for an admin, optionally filtered.

    The search matches a name or an address, ignoring case, so an admin
    can find one member without reading the whole club.

    Rules: R1.5, section 3, section 11 (Members screen).
    """
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
        denied = require(actor, Action.MANAGE_MEMBERS)
        if denied:
            return denied

        query = select(
            schema.members.c.id, schema.members.c.full_name,
            schema.members.c.email, schema.members.c.role,
            schema.members.c.level,
        )
        wanted = (search or "").strip().lower()
        if wanted:
            like = f"%{wanted}%"
            query = query.where(
                func.lower(schema.members.c.full_name).like(like)
                | func.lower(schema.members.c.email).like(like)
            )
        rows = conn.execute(query.order_by(schema.members.c.full_name)).all()
        listed = [
            {
                "id": row.id,
                "full_name": row.full_name,
                "email": row.email,
                "role": row.role,
                "level": row.level,
                "balance": db.ledger_balance(conn, row.id),
            }
            for row in rows
        ]
        return Result.success(f"{len(listed)} members.", listed)


def list_demo_members(engine: Engine) -> list[tuple[int, str, str]]:
    """List (id, name, role) for the demo picker, which has no actor yet.

    Separate from list_members because that one needs an admin, while the
    picker runs with nobody signed in. Reachable only when demo mode is
    allowed, which config.demo_mode_allowed decides.

    Rules: R1.7.
    """
    with engine.begin() as conn:
        rows = conn.execute(
            select(schema.members.c.id, schema.members.c.full_name,
                   schema.members.c.role)
            .order_by(schema.members.c.full_name)
        ).all()
    return [(row.id, row.full_name, row.role) for row in rows]
