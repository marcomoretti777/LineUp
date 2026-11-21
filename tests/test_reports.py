"""Tests for report KPIs, period rules, chart data and admin CSV exports (R12.1-R12.8, A17)."""

import csv
import io
from datetime import date, datetime, timedelta

import pytest
from conftest import give_credits, make_booking, make_member, make_session
from sqlalchemy import insert, select, update

from lineup import db, schema
from lineup.models import Code

NOV_1, NOV_30 = date(2026, 11, 1), date(2026, 11, 30)

BOOKINGS_HEADER = ["session_start", "level", "instructor", "student_email", "status",
                   "attendance", "refunded"]
LEDGER_HEADER = ["created_at", "member_email", "delta", "kind", "ref"]
REQUESTS_HEADER = ["created_at", "member_email", "pack", "credits", "price_eur", "status",
                   "decided_at", "decision_note"]


# Services are imported inside these helpers so a missing module fails each
# test on its own instead of stopping collection.

def _kpis(engine, actor_id, start, end, now):
    from lineup.services.reports import kpis

    return kpis(engine, actor_id, start, end, now=now)


def _chart_data(engine, actor_id, start, end, now):
    from lineup.services.reports import chart_data

    return chart_data(engine, actor_id, start, end, now=now)


def _export(engine, name, actor_id, start=NOV_1, end=NOV_30):
    from lineup.services import reports

    return getattr(reports, name)(engine, actor_id, start, end)


def _parse(data):
    return list(csv.reader(io.StringIO(data.decode("utf-8"))))


# ---------- fixed report dataset ----------

def _booked(engine, member_id, session_id):
    give_credits(engine, member_id, 1)
    return make_booking(engine, member_id, session_id)


def _set_attendance(engine, booking_id, value):
    with engine.begin() as conn:
        conn.execute(update(schema.bookings).where(schema.bookings.c.id == booking_id)
                     .values(attendance=value))


def _cancel(engine, booking_id, session_id, at):
    # Keeps booked_count equal to the confirmed bookings (invariant 1).
    b, s = schema.bookings, schema.surf_sessions
    with engine.begin() as conn:
        conn.execute(update(b).where(b.c.id == booking_id)
                     .values(status="cancelled", cancelled_at=at))
        conn.execute(update(s).where(s.c.id == session_id)
                     .values(booked_count=s.c.booked_count - 1))


def _called_off(engine, instructor, start, category):
    session_id = make_session(engine, instructor, start, status="called_off")
    with engine.begin() as conn:
        conn.execute(update(schema.surf_sessions)
                     .where(schema.surf_sessions.c.id == session_id)
                     .values(call_off_category=category, call_off_reason="Test reason",
                             called_off_at=start - timedelta(hours=4)))
    return session_id


def _request(engine, member_id, credits, status, created_at, decided_at=None,
             decided_by=None, note=None):
    # Built straight on the tables so these tests never depend on the credits service.
    p, r = schema.credit_packs, schema.credit_requests
    with engine.begin() as conn:
        pack_id = conn.execute(select(p.c.id).where(p.c.credits == credits)).scalar_one()
        request_id = conn.execute(insert(r).values(
            member_id=member_id, pack_id=pack_id, payment_ref="MBWAY 912", status=status,
            created_at=created_at, decided_at=decided_at, decided_by=decided_by,
            decision_note=note,
        )).inserted_primary_key[0]
        if status == "approved":
            db.ledger_add(conn, member_id, credits, "purchase", f"purchase:{request_id}")
    return request_id


def _stamp_ledger(engine, at):
    # Ledger rows default to the real clock; a fixed time keeps the period filter stable.
    with engine.begin() as conn:
        conn.execute(update(schema.credit_ledger).values(created_at=at))


@pytest.fixture
def dataset(engine):
    """The fixed November dataset; every expected number is written in the tests."""
    admin = make_member(engine, role="admin", name="Board Admin", email="admin@novasbe.pt")
    instructor = make_member(engine, role="instructor", name="Tiago Reis",
                             email="tiago@novasbe.pt")
    a, b, c, d, e = (make_member(engine, name=f"Student {x}", email=f"{x}@novasbe.pt")
                     for x in "abcde")

    # Ran: S1 Beginner 4/4 (3 attended, 1 no-show); S2 Intermediate 2/4 plus a cancel.
    s1 = make_session(engine, instructor, datetime(2026, 11, 16, 10, 0), capacity=4)
    for member, mark in [(a, "attended"), (b, "attended"), (c, "attended"), (d, "no_show")]:
        _set_attendance(engine, _booked(engine, member, s1), mark)
    s2 = make_session(engine, instructor, datetime(2026, 11, 18, 10, 0), capacity=4,
                      level="intermediate")
    _booked(engine, a, s2)
    _booked(engine, b, s2)
    _cancel(engine, _booked(engine, c, s2), s2, datetime(2026, 11, 15, 10, 0))
    # Future: in the period, not run yet.
    s3 = make_session(engine, instructor, datetime(2026, 11, 23, 10, 0), capacity=4)
    _booked(engine, e, s3)
    # Ran, but before the period.
    s0 = make_session(engine, instructor, datetime(2026, 10, 20, 10, 0), capacity=4)
    _set_attendance(engine, _booked(engine, e, s0), "no_show")
    # Call-offs in the period.
    _called_off(engine, instructor, datetime(2026, 11, 12, 10, 0), "conditions")
    _called_off(engine, instructor, datetime(2026, 11, 13, 10, 0), "conditions")
    _called_off(engine, instructor, datetime(2026, 11, 17, 14, 0), "other")

    _request(engine, a, 5, "approved", datetime(2026, 11, 9, 12, 0),
             decided_at=datetime(2026, 11, 10, 9, 0), decided_by=admin)
    _request(engine, b, 1, "approved", datetime(2026, 11, 11, 12, 0),
             decided_at=datetime(2026, 11, 12, 9, 0), decided_by=admin)
    _request(engine, c, 10, "approved", datetime(2026, 10, 19, 12, 0),
             decided_at=datetime(2026, 10, 20, 9, 0), decided_by=admin)
    _request(engine, d, 1, "pending", datetime(2026, 11, 18, 12, 0))
    _request(engine, b, 5, "rejected", datetime(2026, 11, 14, 12, 0),
             decided_at=datetime(2026, 11, 14, 15, 0), decided_by=admin,
             note='=HYPERLINK("x")')
    _stamp_ledger(engine, datetime(2026, 11, 15, 12, 0))

    return {"admin": admin, "instructor": instructor, "student": a}


@pytest.fixture
def admin(engine):
    return make_member(engine, role="admin")


# ---------- R12.1 period ----------

@pytest.mark.parametrize("start, end, ok", [
    (NOV_1, NOV_1 + timedelta(days=91), True),     # exactly 92 days, both ends counted
    (NOV_1, NOV_1 + timedelta(days=92), False),    # 93 days
    (NOV_30, NOV_1, False),                        # end before start
    (NOV_1, NOV_1, True),                          # a single day
])
def test_r12_1_validate_period(start, end, ok):
    from lineup.logic.reports import validate_period

    refused = validate_period(start, end)

    if ok:
        assert refused is None
    else:
        assert refused.code == Code.INVALID


def test_r12_1_kpis_93_day_period_is_invalid(engine, admin, now):
    result = _kpis(engine, admin, NOV_1, NOV_1 + timedelta(days=92), now)

    assert not result.ok
    assert result.code == Code.INVALID


def test_r12_1_kpis_end_before_start_is_invalid(engine, admin, now):
    result = _kpis(engine, admin, NOV_30, NOV_1, now)

    assert not result.ok
    assert result.code == Code.INVALID


def test_r12_1_kpis_exactly_92_days_is_ok(engine, admin, now):
    result = _kpis(engine, admin, NOV_1, NOV_1 + timedelta(days=91), now)

    assert result.ok


def test_r12_1_exports_refuse_an_invalid_period(engine, admin):
    result = _export(engine, "bookings_csv", admin, NOV_30, NOV_1)

    assert not result.ok
    assert result.code == Code.INVALID


# ---------- R12.2-R12.6 KPIs on the fixed dataset ----------

def test_r12_2_sessions_run_excludes_future_and_called_off(engine, dataset, now):
    result = _kpis(engine, dataset["admin"], NOV_1, NOV_30, now)

    assert result.ok
    assert result.data["sessions_run"] == 2


def test_r12_3_fill_rate_six_of_eight_places(engine, dataset, now):
    result = _kpis(engine, dataset["admin"], NOV_1, NOV_30, now)

    assert result.data["fill_rate"] == pytest.approx(0.75)


def test_r12_3_fill_rate_without_sessions_is_none(engine, admin, now):
    result = _kpis(engine, admin, NOV_1, NOV_30, now)

    assert result.ok
    assert result.data["sessions_run"] == 0
    assert result.data["fill_rate"] is None


def test_r12_4_no_show_rate_one_of_four(engine, dataset, now):
    result = _kpis(engine, dataset["admin"], NOV_1, NOV_30, now)

    assert result.data["no_show_rate"] == pytest.approx(0.25)


def test_r12_4_no_show_rate_nothing_marked_is_none(engine, now):
    admin = make_member(engine, role="admin")
    instructor = make_member(engine, role="instructor")
    session_id = make_session(engine, instructor, datetime(2026, 11, 16, 10, 0))
    _booked(engine, make_member(engine), session_id)

    result = _kpis(engine, admin, NOV_1, NOV_30, now)

    assert result.data["sessions_run"] == 1
    assert result.data["no_show_rate"] is None


def test_r12_5_credits_sold_and_revenue_in_period(engine, dataset, now):
    result = _kpis(engine, dataset["admin"], NOV_1, NOV_30, now)

    assert result.data["credits_sold"] == 6
    assert result.data["revenue_cents"] == 8000


def test_r12_6_calloffs_by_category(engine, dataset, now):
    result = _kpis(engine, dataset["admin"], NOV_1, NOV_30, now)

    assert result.data["calloffs"] == {"conditions": 2, "other": 1}


def test_a17_report_numbers_on_the_fixed_dataset(engine, dataset, now):
    result = _kpis(engine, dataset["admin"], NOV_1, NOV_30, now)

    assert result.ok
    assert result.data == {
        "sessions_run": 2,
        "fill_rate": pytest.approx(0.75),
        "no_show_rate": pytest.approx(0.25),
        "credits_sold": 6,
        "revenue_cents": 8000,
        "calloffs": {"conditions": 2, "other": 1},
    }


# ---------- chart data ----------

def test_bookings_per_week_counts_confirmed_by_iso_week(engine, dataset, now):
    result = _chart_data(engine, dataset["admin"], NOV_1, NOV_30, now)

    assert result.ok
    assert result.data["bookings_per_week"] == {"2026-W47": 6, "2026-W48": 1}


def test_chart_fill_rate_by_level(engine, dataset, now):
    result = _chart_data(engine, dataset["admin"], NOV_1, NOV_30, now)

    assert result.data["fill_rate_by_level"] == {"beginner": pytest.approx(1.0),
                                                 "intermediate": pytest.approx(0.5)}
    assert result.data["calloffs_by_category"] == {"conditions": 2, "other": 1}


def test_bookings_per_week_pure_function():
    from lineup.logic.reports import bookings_per_week

    starts = [datetime(2026, 11, 16, 10), datetime(2026, 11, 22, 18), datetime(2026, 11, 23, 9)]

    assert bookings_per_week(starts) == {"2026-W47": 2, "2026-W48": 1}


# ---------- R12.7 CSV exports ----------

def test_r12_7_bookings_csv_header_and_rows(engine, dataset):
    result = _export(engine, "bookings_csv", dataset["admin"])

    assert result.ok
    rows = _parse(result.data)
    assert rows[0] == BOOKINGS_HEADER
    # S1 4, S2 3 (one cancelled), S3 1; October and called-off sessions excluded.
    assert len(rows) - 1 == 8
    first = rows[1]
    assert first[:4] == ["2026-11-16 10:00", "beginner", "Tiago Reis", "a@novasbe.pt"]
    assert {r[4] for r in rows[1:]} == {"confirmed", "cancelled"}
    assert {r[6] for r in rows[1:]} == {"no"}


def test_r12_7_ledger_csv_header_and_numbers_stay_numbers(engine, dataset):
    result = _export(engine, "ledger_csv", dataset["admin"])

    assert result.ok
    rows = _parse(result.data)
    assert rows[0] == LEDGER_HEADER
    deltas = [r[2] for r in rows[1:]]
    assert "-1" in deltas
    assert not any(d.startswith("'") for d in deltas)


def test_r12_7_requests_csv_header_and_formula_escaping(engine, dataset):
    result = _export(engine, "requests_csv", dataset["admin"])

    assert result.ok
    rows = _parse(result.data)
    assert rows[0] == REQUESTS_HEADER
    # Created in November: the 5-pack, the 1-pack, the pending and the rejected one.
    assert len(rows) - 1 == 4
    assert ["2026-11-09 12:00", "a@novasbe.pt", "5 sessions", "5", "65.00", "approved",
            "2026-11-10 09:00", ""] in rows
    notes = [r[7] for r in rows[1:]]
    assert "'=HYPERLINK(\"x\")" in notes
    assert "=HYPERLINK(\"x\")" not in notes


# ---------- R12.8 admin only ----------

@pytest.mark.parametrize("who", ["instructor", "student"])
@pytest.mark.parametrize("name", ["bookings_csv", "ledger_csv", "requests_csv"])
def test_r12_8_non_admin_cannot_export(engine, dataset, who, name):
    result = _export(engine, name, dataset[who])

    assert not result.ok
    assert result.code == Code.FORBIDDEN


@pytest.mark.parametrize("who", ["instructor", "student"])
def test_r12_8_non_admin_cannot_view_kpis(engine, dataset, now, who):
    result = _kpis(engine, dataset[who], NOV_1, NOV_30, now)

    assert not result.ok
    assert result.code == Code.FORBIDDEN
