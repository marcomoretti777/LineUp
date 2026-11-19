"""Member actions: first-login profiles, roles and levels. Owner: the lead.

Follows the service pattern in docs/contract.md: load the actor, check the
permission, apply the rule, write and notify in one transaction, return a
Result.
"""

from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from lineup import schema
from lineup.logic.accounts import normalise_email, normalise_name, validate_name
from lineup.models import Code, Level, Result, Role


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
    seeded with, so logging in never demotes an admin.

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

        seeded = conn.execute(
            select(schema.members.c.id)
            .where(schema.members.c.email == address)
            .where(schema.members.c.auth_user_id.is_(None))
        ).scalar_one_or_none()
        if seeded is not None:
            conn.execute(
                update(schema.members)
                .where(schema.members.c.id == seeded)
                .values(auth_user_id=auth_user_id)
            )
            return Result.success("Signed in.", seeded)

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
