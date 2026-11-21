"""Inbox actions: list, count and mark read a member's own notifications. Owner: Member 4.

Follows the service pattern in docs/contract.md. Every query filters by the
actor's own id, so no argument can reach another member's inbox (R11.3).
Writing notifications is db.notify, called inside each action's transaction.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.engine import Connection, Engine

from lineup import db, schema
from lineup.models import Actor, Code, Result, fill
from lineup.permissions import Action, require
from lineup.timeutil import utcnow

INBOX_LIMIT = 50


def _authorise(conn: Connection, actor_id: int) -> tuple[Actor | None, Result | None]:
    actor = db.get_actor(conn, actor_id)
    if actor is None:
        return None, Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
    return actor, require(actor, Action.READ_NOTIFICATIONS, actor.id)


def _own_notifications(conn: Connection, member_id: int, limit: int) -> list[dict]:
    n = schema.notifications
    rows = conn.execute(
        select(n.c.id, n.c.kind, n.c.message, n.c.created_at, n.c.read_at)
        .where(n.c.member_id == member_id)
        # id breaks ties: several notifications can share a created_at.
        .order_by(n.c.created_at.desc(), n.c.id.desc())
        .limit(limit)
    )
    return [dict(row._mapping) for row in rows]


def _mark_own_read(conn: Connection, member_id: int, now: datetime) -> int:
    n = schema.notifications
    return conn.execute(
        update(n)
        .where(n.c.member_id == member_id, n.c.read_at.is_(None))
        .values(read_at=now)
    ).rowcount


def list_notifications(engine: Engine, actor_id: int, limit: int = INBOX_LIMIT) -> Result:
    """Return the actor's newest notifications as dicts (id, kind, message, created_at, read_at).

    Rules: R11.3.
    """
    with engine.connect() as conn:
        actor, denied = _authorise(conn, actor_id)
        if denied:
            return denied
        items = _own_notifications(conn, actor.id, min(limit, INBOX_LIMIT))
    return Result.success(f"{len(items)} notifications.", items)


def unread(engine: Engine, actor_id: int) -> Result:
    """Return the number of the actor's unread notifications as Result.data.

    Rules: R11.3.
    """
    with engine.connect() as conn:
        actor, denied = _authorise(conn, actor_id)
        if denied:
            return denied
        count = db.unread_count(conn, actor.id)
    return Result.success(f"{count} unread.", count)


def mark_all_read(engine: Engine, actor_id: int, now: datetime | None = None) -> Result:
    """Mark every unread notification of the actor as read at `now`.

    Rules: R11.2, R11.3.
    """
    now = now or utcnow()
    with engine.begin() as conn:
        actor, denied = _authorise(conn, actor_id)
        if denied:
            return denied
        changed = _mark_own_read(conn, actor.id, now)
    return Result.success("All notifications marked as read.", changed)
