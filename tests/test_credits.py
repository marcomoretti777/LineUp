"""Service tests for the credit approval workflow (R10.2-R10.8, R11.1)."""

from conftest import give_credits, make_booking, make_member, make_session
from datetime import timedelta
from sqlalchemy import func, select

from lineup import db, schema
from lineup.models import Code
from lineup.services import credits

FIVE_PACK = 2


def make_request(engine, member_id, now, pack_id=FIVE_PACK, ref="MBWAY 912"):
    """Submit a credit request through the service and return its id."""
    result = credits.request_pack(engine, member_id, pack_id, ref, now=now)
    assert result.ok, result.message
    return result.data["id"]


def request_row(engine, request_id):
    r = schema.credit_requests
    with engine.connect() as conn:
        return conn.execute(select(r).where(r.c.id == request_id)).first()


def count(engine, table, *where):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table).where(*where)).scalar_one()


def ledger_count(engine, member_id):
    return count(engine, schema.credit_ledger, schema.credit_ledger.c.member_id == member_id)


def notification_count(engine, member_id, kind="credits"):
    n = schema.notifications
    return count(engine, n, n.c.member_id == member_id, n.c.kind == kind)


def balance(engine, member_id):
    with engine.connect() as conn:
        return db.ledger_balance(conn, member_id)


def test_list_packs_three_seeded_packs_with_price_per_credit(engine):
    packs = credits.list_packs(engine)
    assert [(p["name"], p["credits"], p["price_cents"]) for p in packs] == [
        ("1 session", 1, 1500), ("5 sessions", 5, 6500), ("10 sessions", 10, 12000),
    ]
    assert [p["price_per_credit_cents"] for p in packs] == [1500, 1300, 1200]


def test_r10_2_request_creates_pending_row(engine, now):
    ana = make_member(engine)
    result = credits.request_pack(engine, ana, FIVE_PACK, "  MBWAY 912 ", now=now)
    assert result.ok
    row = request_row(engine, result.data["id"])
    assert row.status == "pending"
    assert row.member_id == ana
    assert row.payment_ref == "MBWAY 912"
    assert row.created_at == now


def test_r10_2_second_request_while_pending_is_duplicate(engine, now):
    ana = make_member(engine)
    make_request(engine, ana, now)
    result = credits.request_pack(engine, ana, 1, "MBWAY 913", now=now)
    assert result.code == Code.DUPLICATE
    assert count(engine, schema.credit_requests) == 1


def test_r10_3_bad_reference_is_invalid(engine, now):
    ana = make_member(engine)
    for ref in ("<b>x</b>", "ab"):
        result = credits.request_pack(engine, ana, FIVE_PACK, ref, now=now)
        assert result.code == Code.INVALID
    assert count(engine, schema.credit_requests) == 0


def test_r10_2_instructor_request_is_forbidden(engine, now):
    tiago = make_member(engine, role="instructor")
    result = credits.request_pack(engine, tiago, FIVE_PACK, "MBWAY 912", now=now)
    assert result.code == Code.FORBIDDEN
    assert count(engine, schema.credit_requests) == 0


def test_r10_4_withdraw_own_pending(engine, now):
    ana = make_member(engine)
    req = make_request(engine, ana, now)
    result = credits.withdraw_request(engine, ana, req, now=now)
    assert result.ok
    assert request_row(engine, req).status == "withdrawn"


def test_r10_4_withdraw_other_students_request_forbidden(engine, now):
    ana, diogo = make_member(engine), make_member(engine)
    req = make_request(engine, ana, now)
    result = credits.withdraw_request(engine, diogo, req, now=now)
    assert result.code == Code.FORBIDDEN
    assert request_row(engine, req).status == "pending"


def test_r10_4_withdraw_twice_already_done(engine, now):
    ana = make_member(engine)
    req = make_request(engine, ana, now)
    assert credits.withdraw_request(engine, ana, req, now=now).ok
    result = credits.withdraw_request(engine, ana, req, now=now)
    assert result.code == Code.ALREADY_DONE


def test_r10_5_r10_6_admin_approves_once(engine, now):
    ana, marta = make_member(engine), make_member(engine, role="admin")
    req = make_request(engine, ana, now)
    result = credits.approve_request(engine, marta, req, now=now)
    assert result.ok
    row = request_row(engine, req)
    assert row.status == "approved"
    assert row.decided_by == marta
    assert row.decided_at == now
    ledger = schema.credit_ledger
    with engine.connect() as conn:
        entry = conn.execute(select(ledger).where(ledger.c.member_id == ana)).one()
    assert entry.ref == f"purchase:{req}"
    assert entry.delta == 5
    assert entry.kind == "purchase"
    assert balance(engine, ana) == 5
    assert notification_count(engine, ana) == 1


def test_r10_6_approve_twice_already_done_one_ledger_row(engine, now):
    ana, marta = make_member(engine), make_member(engine, role="admin")
    req = make_request(engine, ana, now)
    assert credits.approve_request(engine, marta, req, now=now).ok
    result = credits.approve_request(engine, marta, req, now=now)
    assert result.code == Code.ALREADY_DONE
    assert ledger_count(engine, ana) == 1
    assert balance(engine, ana) == 5
    assert notification_count(engine, ana) == 1


def test_r10_5_student_approve_forbidden(engine, now):
    ana, diogo = make_member(engine), make_member(engine)
    req = make_request(engine, ana, now)
    result = credits.approve_request(engine, diogo, req, now=now)
    assert result.code == Code.FORBIDDEN
    assert request_row(engine, req).status == "pending"
    assert ledger_count(engine, ana) == 0


def test_r10_6_approve_withdrawn_already_done(engine, now):
    ana, marta = make_member(engine), make_member(engine, role="admin")
    req = make_request(engine, ana, now)
    assert credits.withdraw_request(engine, ana, req, now=now).ok
    result = credits.approve_request(engine, marta, req, now=now)
    assert result.code == Code.ALREADY_DONE
    assert request_row(engine, req).status == "withdrawn"
    assert ledger_count(engine, ana) == 0
    assert notification_count(engine, ana) == 0


def test_r10_5_reject_with_note(engine, now):
    ana, marta = make_member(engine), make_member(engine, role="admin")
    req = make_request(engine, ana, now)
    result = credits.reject_request(engine, marta, req, "No payment received", now=now)
    assert result.ok
    row = request_row(engine, req)
    assert row.status == "rejected"
    assert row.decision_note == "No payment received"
    assert row.decided_by == marta
    assert row.decided_at == now
    assert ledger_count(engine, ana) == 0
    assert notification_count(engine, ana) == 1


def test_r10_5_reject_short_note_invalid(engine, now):
    ana, marta = make_member(engine), make_member(engine, role="admin")
    req = make_request(engine, ana, now)
    result = credits.reject_request(engine, marta, req, "no", now=now)
    assert result.code == Code.INVALID
    assert request_row(engine, req).status == "pending"
    assert notification_count(engine, ana) == 0


def test_r10_6_reject_twice_already_done(engine, now):
    ana, marta = make_member(engine), make_member(engine, role="admin")
    req = make_request(engine, ana, now)
    assert credits.reject_request(engine, marta, req, "No payment received", now=now).ok
    result = credits.reject_request(engine, marta, req, "Still no payment", now=now)
    assert result.code == Code.ALREADY_DONE
    assert request_row(engine, req).decision_note == "No payment received"
    assert notification_count(engine, ana) == 1


def test_r10_7_statement_newest_first_running_balance(engine, now):
    ana, marta = make_member(engine), make_member(engine, role="admin")
    tiago = make_member(engine, role="instructor")
    req = make_request(engine, ana, now)
    assert credits.approve_request(engine, marta, req, now=now).ok
    give_credits(engine, ana, 1)
    session = make_session(engine, tiago, now + timedelta(days=1))
    booking = make_booking(engine, ana, session)

    result = credits.statement(engine, ana)
    assert result.ok
    rows = result.data["rows"]
    assert [(r["delta"], r["balance"]) for r in rows] == [(-1, 5), (1, 6), (5, 5)]
    assert rows[0]["ref"] == f"booking:{booking}"
    assert rows[-1]["ref"] == f"purchase:{req}"
    assert result.data["balance"] == 5


def test_r10_7_student_other_statement_forbidden(engine):
    ana, diogo = make_member(engine), make_member(engine)
    give_credits(engine, ana, 2)
    result = credits.statement(engine, diogo, member_id=ana)
    assert result.code == Code.FORBIDDEN


def test_r10_7_admin_sees_any_statement(engine):
    ana, marta = make_member(engine), make_member(engine, role="admin")
    give_credits(engine, ana, 2)
    result = credits.statement(engine, marta, member_id=ana)
    assert result.ok
    assert result.data["balance"] == 2
    assert [r["delta"] for r in result.data["rows"]] == [2]


def test_pending_requests_admin_oldest_first(engine, now):
    ana, diogo = make_member(engine), make_member(engine)
    ines, marta = make_member(engine), make_member(engine, role="admin")
    later = make_request(engine, diogo, now + timedelta(minutes=5))
    first = make_request(engine, ana, now)
    gone = make_request(engine, ines, now + timedelta(minutes=1))
    assert credits.withdraw_request(engine, ines, gone, now=now).ok

    result = credits.pending_requests(engine, marta)
    assert result.ok
    assert [r["id"] for r in result.data] == [first, later]
    assert result.data[0]["credits"] == 5


def test_pending_requests_student_forbidden(engine):
    ana = make_member(engine)
    assert credits.pending_requests(engine, ana).code == Code.FORBIDDEN


def test_my_requests_lists_own_only(engine, now):
    ana, diogo = make_member(engine), make_member(engine)
    mine = make_request(engine, ana, now)
    make_request(engine, diogo, now)
    result = credits.my_requests(engine, ana)
    assert result.ok
    assert [r["id"] for r in result.data] == [mine]
    assert result.data[0]["status"] == "pending"
