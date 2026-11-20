"""Queries the credits lane needs beyond the shared ones in lineup/db.py.

Every function takes an open connection, so the calling service keeps all
its reads and writes in one transaction.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, Row, insert, select, update

from lineup import schema
from lineup.models import RequestStatus


def active_packs(conn: Connection) -> list[Row]:
    """Return the active credit packs, smallest first.

    Rules: R10.1.
    """
    p = schema.credit_packs
    return conn.execute(
        select(p.c.id, p.c.name, p.c.credits, p.c.price_cents)
        .where(p.c.active.is_(True))
        .order_by(p.c.credits, p.c.id)
    ).all()


def get_pack(conn: Connection, pack_id: int) -> Row | None:
    """Return one credit pack, active or not, or None if it does not exist.

    Rules: R10.1, R10.2.
    """
    p = schema.credit_packs
    return conn.execute(
        select(p.c.id, p.c.name, p.c.credits, p.c.price_cents, p.c.active)
        .where(p.c.id == pack_id)
    ).first()


def has_pending(conn: Connection, member_id: int) -> bool:
    """Say whether a member already has a pending credit request.

    Rules: R10.2.
    """
    r = schema.credit_requests
    return conn.execute(
        select(r.c.id).where(
            r.c.member_id == member_id, r.c.status == RequestStatus.PENDING.value
        )
    ).first() is not None


def insert_request(conn: Connection, member_id: int, pack_id: int, payment_ref: str,
                   now: datetime) -> int:
    """Insert a pending credit request and return its id.

    Rules: R10.2, R10.3.
    """
    r = schema.credit_requests
    return conn.execute(
        insert(r).values(
            member_id=member_id, pack_id=pack_id, payment_ref=payment_ref,
            status=RequestStatus.PENDING.value, created_at=now,
        )
    ).inserted_primary_key[0]


def get_request(conn: Connection, request_id: int, for_update: bool = False) -> Row | None:
    """Return a credit request with its pack's name and credits, or None.

    With for_update the row stays locked until the transaction ends, so two
    admins deciding the same request at once are served one after the other.

    Rules: R10.4-R10.6.
    """
    r, p = schema.credit_requests, schema.credit_packs
    query = (
        select(
            r.c.id, r.c.member_id, r.c.pack_id, r.c.payment_ref, r.c.status,
            r.c.decided_by, r.c.decided_at, r.c.decision_note, r.c.created_at,
            p.c.name.label("pack_name"), p.c.credits,
        )
        .join(p, p.c.id == r.c.pack_id)
        .where(r.c.id == request_id)
    )
    if for_update:
        query = query.with_for_update(of=r)
    return conn.execute(query).first()


def set_status(conn: Connection, request_id: int, status: RequestStatus, *,
               decided_by: int | None = None, decided_at: datetime | None = None,
               note: str | None = None) -> bool:
    """Move a pending request to a new status; return False if it was not pending.

    Rules: R10.4, R10.5, R10.6.
    """
    r = schema.credit_requests
    values: dict = {"status": RequestStatus(status).value}
    if decided_by is not None:
        values.update(decided_by=decided_by, decided_at=decided_at)
    if note is not None:
        values["decision_note"] = note
    changed = conn.execute(
        update(r)
        .where(r.c.id == request_id, r.c.status == RequestStatus.PENDING.value)
        .values(**values)
    )
    return changed.rowcount == 1


def _request_listing():
    r, p, m = schema.credit_requests, schema.credit_packs, schema.members
    return (
        select(
            r.c.id, r.c.member_id, m.c.full_name, m.c.email, r.c.pack_id,
            p.c.name.label("pack_name"), p.c.credits, p.c.price_cents,
            r.c.payment_ref, r.c.status, r.c.decision_note, r.c.decided_at, r.c.created_at,
        )
        .join(p, p.c.id == r.c.pack_id)
        .join(m, m.c.id == r.c.member_id)
    )


def pending_with_members(conn: Connection) -> list[Row]:
    """Return every pending request with its member and pack, oldest first.

    Rules: R10.5.
    """
    r = schema.credit_requests
    return conn.execute(
        _request_listing()
        .where(r.c.status == RequestStatus.PENDING.value)
        .order_by(r.c.created_at, r.c.id)
    ).all()


def requests_for_member(conn: Connection, member_id: int) -> list[Row]:
    """Return a member's credit requests, newest first.

    Rules: R10.2, R10.4.
    """
    r = schema.credit_requests
    return conn.execute(
        _request_listing()
        .where(r.c.member_id == member_id)
        .order_by(r.c.created_at.desc(), r.c.id.desc())
    ).all()


def ledger_rows(conn: Connection, member_id: int) -> list[Row]:
    """Return a member's ledger rows, oldest first.

    Rules: R10.7, R10.8.
    """
    ledger = schema.credit_ledger
    return conn.execute(
        select(
            ledger.c.id, ledger.c.delta, ledger.c.kind, ledger.c.ref,
            ledger.c.note, ledger.c.created_at,
        )
        .where(ledger.c.member_id == member_id)
        .order_by(ledger.c.created_at, ledger.c.id)
    ).all()
