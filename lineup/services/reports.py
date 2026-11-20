"""Admin reports: KPIs, chart data and CSV exports. Owner: Member 4 (Credits and reports lane)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta

from sqlalchemy import Connection, Engine

from lineup import db
from lineup.logic import reports as rules
from lineup.models import Code, Result, fill
from lineup.permissions import Action, require
from lineup.queries import reports as q
from lineup.timeutil import from_local, to_local, utcnow

BOOKINGS_HEADER = ("session_start", "level", "instructor", "student_email", "status",
                   "attendance", "refunded")
LEDGER_HEADER = ("created_at", "member_email", "delta", "kind", "ref")
REQUESTS_HEADER = ("created_at", "member_email", "pack", "credits", "price_eur", "status",
                   "decided_at", "decision_note")


def _utc_range(start: date, end: date) -> tuple[datetime, datetime]:
    # Lisbon days, both counted: from start 00:00 up to (not including) the day after end.
    return from_local(start, time(0)), from_local(end + timedelta(days=1), time(0))


def _local_text(dt: datetime | None) -> str:
    return "" if dt is None else to_local(dt).strftime("%Y-%m-%d %H:%M")


def _open(conn: Connection, actor_id: int, start: date, end: date) -> Result | None:
    # Shared opening of every report: actor, admin permission, then the period rule.
    actor = db.get_actor(conn, actor_id)
    if actor is None:
        return Result.fail(Code.NOT_FOUND, fill(Code.NOT_FOUND))
    denied = require(actor, Action.VIEW_REPORTS)
    if denied:
        return denied
    return rules.validate_period(start, end)


def _period_text(start: date, end: date) -> str:
    return f"{start:%d %b %Y} to {end:%d %b %Y}"


def kpis(engine: Engine, actor_id: int, start: date, end: date,
         now: datetime | None = None) -> Result:
    """Return the report numbers for a period of Lisbon dates, both ends included.

    data has sessions_run, fill_rate and no_show_rate (None when there is
    nothing to divide, shown as "—"), credits_sold, revenue_cents and calloffs.

    Rules: R12.1, R12.2, R12.3, R12.4, R12.5, R12.6.
    """
    now = now or utcnow()
    with engine.begin() as conn:
        refused = _open(conn, actor_id, start, end)
        if refused:
            return refused
        lo, hi = _utc_range(start, end)
        run = q.sessions_run(conn, lo, hi, now)
        approved = q.approved_requests(conn, lo, hi)
        data = {
            "sessions_run": len(run),
            "fill_rate": rules.fill_rate(run),
            "no_show_rate": rules.no_show_rate(q.attendance_marks(conn, [s.id for s in run])),
            "credits_sold": rules.credits_sold(approved),
            "revenue_cents": rules.revenue_cents(approved),
            "calloffs": rules.calloffs_by_category(q.calloff_categories(conn, lo, hi)),
        }
    return Result.success(f"Report for {_period_text(start, end)}.", data)


def chart_data(engine: Engine, actor_id: int, start: date, end: date,
               now: datetime | None = None) -> Result:
    """Return the data behind the report charts for a period of Lisbon dates.

    data has bookings_per_week ({"2026-W47": n}), fill_rate_by_level (levels
    with sessions run only) and calloffs_by_category.

    Rules: R12.1, R12.2, R12.3, R12.6.
    """
    now = now or utcnow()
    with engine.begin() as conn:
        refused = _open(conn, actor_id, start, end)
        if refused:
            return refused
        lo, hi = _utc_range(start, end)
        data = {
            "bookings_per_week": rules.bookings_per_week(q.confirmed_booking_starts(conn, lo, hi)),
            "fill_rate_by_level": rules.fill_rate_by_level(q.sessions_run(conn, lo, hi, now)),
            "calloffs_by_category": rules.calloffs_by_category(q.calloff_categories(conn, lo, hi)),
        }
    return Result.success(f"Charts for {_period_text(start, end)}.", data)


def _export(engine: Engine, actor_id: int, start: date, end: date, what: str,
            header: tuple[str, ...], fetch: Callable, to_row: Callable) -> Result:
    with engine.begin() as conn:
        refused = _open(conn, actor_id, start, end)
        if refused:
            return refused
        lo, hi = _utc_range(start, end)
        rows = [to_row(r) for r in fetch(conn, lo, hi)]
    text = rules.to_csv(header, rows)
    return Result.success(
        f"{what} CSV for {_period_text(start, end)}: {len(rows)} rows.", text.encode("utf-8"),
    )


def bookings_csv(engine: Engine, actor_id: int, start: date, end: date) -> Result:
    """Export every booking whose session starts in the period as formula-safe CSV bytes.

    Rules: R12.1, R12.7, R12.8.
    """
    return _export(
        engine, actor_id, start, end, "Bookings", BOOKINGS_HEADER, q.bookings_export_rows,
        lambda r: (_local_text(r.starts_at), r.level, r.instructor, r.student_email, r.status,
                   r.attendance, "yes" if r.refunded else "no"),
    )


def ledger_csv(engine: Engine, actor_id: int, start: date, end: date) -> Result:
    """Export the ledger rows created in the period as formula-safe CSV bytes.

    Rules: R10.8, R12.1, R12.7, R12.8.
    """
    return _export(
        engine, actor_id, start, end, "Ledger", LEDGER_HEADER, q.ledger_export_rows,
        lambda r: (_local_text(r.created_at), r.member_email, r.delta, r.kind, r.ref),
    )


def requests_csv(engine: Engine, actor_id: int, start: date, end: date) -> Result:
    """Export the credit requests created in the period as formula-safe CSV bytes.

    Rules: R12.1, R12.5, R12.7, R12.8.
    """
    return _export(
        engine, actor_id, start, end, "Requests", REQUESTS_HEADER, q.requests_export_rows,
        lambda r: (_local_text(r.created_at), r.member_email, r.pack, r.credits,
                   rules.eur_text(r.price_cents), r.status, _local_text(r.decided_at),
                   r.decision_note),
    )
