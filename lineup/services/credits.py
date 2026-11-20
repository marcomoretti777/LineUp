"""Credit packs, requests, approvals and statements (R10, R11.1).

Each action follows the contract's service pattern: load the actor, check
the permission, ask the pure rule, then write and notify in one transaction.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Engine

from lineup import db
from lineup.logic import credits as rules
from lineup.models import Code, LedgerKind, RequestStatus, Result, fill
from lineup.permissions import Action, require
from lineup.queries import credits as q
from lineup.timeutil import utcnow

NOTIFY_KIND = "credits"


def _not_found() -> Result:
    return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))


def _already_done() -> Result:
    return Result.fail(Code.ALREADY_DONE, fill(Code.ALREADY_DONE))


def list_packs(engine: Engine) -> list[dict]:
    """Return the active credit packs with their price and price per credit.

    Rules: R10.1.
    """
    with engine.connect() as conn:
        packs = q.active_packs(conn)
    return [
        {
            "id": p.id,
            "name": p.name,
            "credits": p.credits,
            "price_cents": p.price_cents,
            "price": rules.fmt_eur(p.price_cents),
            "price_per_credit_cents": rules.price_per_credit_cents(p.price_cents, p.credits),
            "price_per_credit": rules.fmt_eur(
                rules.price_per_credit_cents(p.price_cents, p.credits)
            ),
        }
        for p in packs
    ]


def request_pack(engine: Engine, actor_id: int, pack_id: int, payment_ref: str,
                 now: datetime | None = None) -> Result:
    """Submit a pending request for a credit pack with a payment reference.

    Rules: R10.2, R10.3, section 3 (REQUEST_CREDITS).
    """
    now = now or utcnow()
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return _not_found()
        denied = require(actor, Action.REQUEST_CREDITS, owner_id=actor.id)
        if denied:
            return denied
        ref, invalid = rules.validate_payment_ref(payment_ref)
        if invalid:
            return invalid
        pack = q.get_pack(conn, pack_id)
        refused = rules.check_can_request(
            role=actor.role,
            has_pending=q.has_pending(conn, actor.id),
            pack_active=pack is not None and bool(pack.active),
        )
        if refused:
            return refused
        request_id = q.insert_request(conn, actor.id, pack.id, ref, now)
        return Result.success(
            f"Request sent for {pack.name}. An admin will check your payment.",
            {"id": request_id},
        )


def withdraw_request(engine: Engine, actor_id: int, request_id: int,
                     now: datetime | None = None) -> Result:
    """Withdraw the actor's own pending credit request.

    Rules: R10.4, section 3 (WITHDRAW_REQUEST).
    """
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return _not_found()
        req = q.get_request(conn, request_id, for_update=True)
        if req is None:
            return _not_found()
        denied = require(actor, Action.WITHDRAW_REQUEST, owner_id=req.member_id)
        if denied:
            return denied
        refused = rules.check_can_withdraw(
            is_owner=req.member_id == actor.id, status=RequestStatus(req.status)
        )
        if refused:
            return refused
        if not q.set_status(conn, req.id, RequestStatus.WITHDRAWN):
            return _already_done()
        return Result.success("Request withdrawn.", {"id": req.id})


def approve_request(engine: Engine, actor_id: int, request_id: int,
                    now: datetime | None = None) -> Result:
    """Approve a pending request, add the pack's credits once and notify the member.

    Rules: R10.5, R10.6, R10.8, R11.1, section 3 (DECIDE_CREDITS).
    """
    now = now or utcnow()
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return _not_found()
        denied = require(actor, Action.DECIDE_CREDITS)
        if denied:
            return denied
        req = q.get_request(conn, request_id, for_update=True)
        if req is None:
            return _not_found()
        refused = rules.check_can_decide(status=RequestStatus(req.status))
        if refused:
            return refused
        # The unique purchase ref is the guard against double credit, so the
        # ledger write comes first and a False means nothing else is written.
        if not db.ledger_add(conn, req.member_id, req.credits, LedgerKind.PURCHASE,
                             f"purchase:{req.id}"):
            return _already_done()
        q.set_status(conn, req.id, RequestStatus.APPROVED, decided_by=actor.id, decided_at=now)
        db.notify(
            conn, req.member_id, NOTIFY_KIND,
            f"Your request for {req.pack_name} was approved: "
            f"{req.credits} credits added.",
        )
        return Result.success(
            f"Approved: {req.credits} credits added.", {"id": req.id}
        )


def reject_request(engine: Engine, actor_id: int, request_id: int, note: str,
                   now: datetime | None = None) -> Result:
    """Reject a pending request with a note and notify the member.

    Rules: R10.5, R10.6, R11.1, section 3 (DECIDE_CREDITS).
    """
    now = now or utcnow()
    with engine.begin() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return _not_found()
        denied = require(actor, Action.DECIDE_CREDITS)
        if denied:
            return denied
        invalid = rules.validate_note(note)
        if invalid:
            return invalid
        req = q.get_request(conn, request_id, for_update=True)
        if req is None:
            return _not_found()
        refused = rules.check_can_decide(status=RequestStatus(req.status))
        if refused:
            return refused
        clean = note.strip()
        if not q.set_status(conn, req.id, RequestStatus.REJECTED,
                            decided_by=actor.id, decided_at=now, note=clean):
            return _already_done()
        db.notify(
            conn, req.member_id, NOTIFY_KIND,
            f"Your request for {req.pack_name} was rejected: {clean}",
        )
        return Result.success("Request rejected.", {"id": req.id})


def _request_dict(row) -> dict:
    return {
        "id": row.id,
        "member_id": row.member_id,
        "member_name": row.full_name,
        "member_email": row.email,
        "pack_id": row.pack_id,
        "pack_name": row.pack_name,
        "credits": row.credits,
        "price_cents": row.price_cents,
        "price": rules.fmt_eur(row.price_cents),
        "payment_ref": row.payment_ref,
        "status": row.status,
        "decision_note": row.decision_note,
        "decided_at": row.decided_at,
        "created_at": row.created_at,
    }


def pending_requests(engine: Engine, actor_id: int) -> Result:
    """List every pending credit request, oldest first, for an admin.

    Rules: R10.5, section 3 (DECIDE_CREDITS).
    """
    with engine.connect() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return _not_found()
        denied = require(actor, Action.DECIDE_CREDITS)
        if denied:
            return denied
        rows = q.pending_with_members(conn)
    return Result.success(f"{len(rows)} pending.", [_request_dict(r) for r in rows])


def my_requests(engine: Engine, actor_id: int) -> Result:
    """List the actor's own credit requests, newest first.

    Rules: R10.2, R10.4, section 3 (REQUEST_CREDITS).
    """
    with engine.connect() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return _not_found()
        denied = require(actor, Action.REQUEST_CREDITS, owner_id=actor.id)
        if denied:
            return denied
        rows = q.requests_for_member(conn, actor.id)
    return Result.success(f"{len(rows)} requests.", [_request_dict(r) for r in rows])


def statement(engine: Engine, actor_id: int, member_id: int | None = None) -> Result:
    """Return a member's ledger rows newest first, each with the balance after it.

    Rules: R10.7, R10.8, section 3 (VIEW_STATEMENT).
    """
    with engine.connect() as conn:
        actor = db.get_actor(conn, actor_id)
        if actor is None:
            return _not_found()
        target = actor.id if member_id is None else member_id
        denied = require(actor, Action.VIEW_STATEMENT, owner_id=target)
        if denied:
            return denied
        if target != actor.id and db.get_actor(conn, target) is None:
            return _not_found()
        rows = q.ledger_rows(conn, target)
    running = 0
    out = []
    for row in rows:
        running += row.delta
        out.append({
            "id": row.id, "created_at": row.created_at, "kind": row.kind,
            "delta": row.delta, "ref": row.ref, "note": row.note, "balance": running,
        })
    out.reverse()
    return Result.success(
        f"Balance: {running} credits.",
        {"member_id": target, "balance": running, "rows": out},
    )
