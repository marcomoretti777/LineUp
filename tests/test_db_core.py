"""Tests for the schema, shared queries and invariant checks (spec section 9).

Tests that corrupt data on purpose use `raw_engine`, which the automatic
invariant check in conftest does not watch.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, insert, inspect, select, update
from sqlalchemy.exc import IntegrityError

from conftest import give_credits, make_booking, make_member, make_session

TABLES = {
    "members", "surf_sessions", "bookings", "waitlist_entries", "credit_packs",
    "credit_requests", "credit_ledger", "notifications", "forecast_hours",
    "forecast_days", "condition_thresholds", "app_settings",
}


@pytest.fixture
def raw_engine():
    """Like `engine`, but not checked for invariants after the test."""
    from lineup import db

    eng = db.make_engine("sqlite://")
    db.init_db(eng)
    yield eng
    eng.dispose()


def db():
    from lineup import db as module

    return module


def schema():
    from lineup import schema as module

    return module


def count(engine, table, *where):
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table).where(*where)).scalar_one()


# ---- Engine and tables ----


def test_section9_init_db_creates_all_twelve_tables(engine):
    assert set(inspect(engine).get_table_names()) == TABLES


def test_section9_init_db_twice_is_harmless(engine):
    db().init_db(engine)
    s = schema()
    assert count(engine, s.credit_packs) == 3
    assert count(engine, s.condition_thresholds) == 2


def test_r10_1_init_db_seeds_the_three_credit_packs(engine):
    from lineup.config import CREDIT_PACKS

    s = schema()
    with engine.connect() as conn:
        rows = conn.execute(
            select(s.credit_packs.c.name, s.credit_packs.c.credits, s.credit_packs.c.price_cents)
            .order_by(s.credit_packs.c.credits)
        ).all()
    assert [tuple(r) for r in rows] == CREDIT_PACKS


def test_r6_init_db_seeds_the_default_thresholds(engine):
    from lineup.config import DEFAULT_THRESHOLDS

    t = schema().condition_thresholds
    with engine.connect() as conn:
        rows = conn.execute(select(
            t.c.level, t.c.go_wave_m, t.c.go_wind_kmh, t.c.marginal_wave_m, t.c.marginal_wind_kmh,
        )).all()
    assert {r[0]: tuple(r[1:]) for r in rows} == DEFAULT_THRESHOLDS


def test_section9_init_db_leaves_existing_packs_alone(engine):
    s = schema()
    with engine.begin() as conn:
        conn.execute(s.credit_packs.delete())
        conn.execute(insert(s.credit_packs).values(name="Club deal", credits=3, price_cents=4000))
    db().init_db(engine)
    with engine.connect() as conn:
        names = conn.execute(select(s.credit_packs.c.name)).scalars().all()
    assert names == ["Club deal"]


def test_section8_make_engine_without_url_creates_the_data_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    eng = db().make_engine()
    try:
        assert eng.dialect.name == "sqlite"
        assert (tmp_path / "data").is_dir()
    finally:
        eng.dispose()


def test_section9_sqlite_enforces_foreign_keys(engine):
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert(schema().bookings).values(
                session_id=999, member_id=999, status="confirmed",
            ))


def test_section9_check_constraint_refuses_capacity_nine(engine):
    instructor = make_member(engine, role="instructor")
    with pytest.raises(IntegrityError):
        make_session(engine, instructor, datetime(2026, 11, 21, 10, 0), capacity=9)


# ---- Row Level Security (spec section 12) ----


def test_section12_rls_statements_empty_on_sqlite():
    assert db().rls_statements("sqlite") == []


def test_section12_rls_statements_cover_every_table_on_postgres():
    statements = db().rls_statements("postgresql")
    assert len(statements) == 12
    assert {s.split()[2].strip('"') for s in statements} == TABLES
    assert all(s.endswith("ENABLE ROW LEVEL SECURITY") for s in statements)


# ---- Ledger (R10.7, R10.8) ----


def test_r10_8_ledger_add_refuses_a_second_row_with_the_same_ref(engine):
    member = make_member(engine)
    with engine.begin() as conn:
        assert db().ledger_add(conn, member, 5, "purchase", "purchase:1") is True
        assert db().ledger_add(conn, member, 5, "purchase", "purchase:1") is False
    ledger = schema().credit_ledger
    assert count(engine, ledger, ledger.c.ref == "purchase:1") == 1


def test_r10_7_ledger_balance_is_the_sum_of_deltas(engine):
    member = make_member(engine)
    other = make_member(engine)
    with engine.begin() as conn:
        db().ledger_add(conn, member, 5, "purchase", "purchase:1")
        db().ledger_add(conn, member, -1, "booking", "booking:1")
        db().ledger_add(conn, member, 1, "refund", "refund:1")
        db().ledger_add(conn, other, 10, "purchase", "purchase:2")
    with engine.connect() as conn:
        assert db().ledger_balance(conn, member) == 5
        assert db().ledger_balance(conn, make_member(engine)) == 0


def test_r10_8_ledger_unique_ref_blocks_a_raw_duplicate(engine):
    member = make_member(engine)
    give_credits(engine, member, 2)
    ledger = schema().credit_ledger
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert(ledger).values(member_id=member, delta=1, kind="refund", ref="refund:57"))
            conn.execute(insert(ledger).values(member_id=member, delta=1, kind="refund", ref="refund:57"))


# ---- Notifications (R11) ----


def test_r11_notify_counts_as_unread_only_for_that_member(engine):
    ana = make_member(engine)
    bruno = make_member(engine)
    with engine.begin() as conn:
        db().notify(conn, ana, "booking", "Booked: Fri 20 Nov, 10:00.")
    with engine.connect() as conn:
        assert db().unread_count(conn, ana) == 1
        assert db().unread_count(conn, bruno) == 0


def test_section9_notify_shortens_messages_to_300_characters(engine):
    ana = make_member(engine)
    with engine.begin() as conn:
        db().notify(conn, ana, "booking", "x" * 400)
    with engine.connect() as conn:
        message = conn.execute(select(schema().notifications.c.message)).scalar_one()
    assert len(message) == 300
    assert message.endswith("…")


def test_r11_2_notification_rolls_back_with_its_action(engine):
    ana = make_member(engine)
    with pytest.raises(RuntimeError):
        with engine.begin() as conn:
            db().notify(conn, ana, "booking", "Booked.")
            raise RuntimeError("action failed after notifying")
    with engine.connect() as conn:
        assert db().unread_count(conn, ana) == 0


# ---- Actors and sessions ----


def test_section8_get_actor_returns_role_and_level(engine):
    from lineup.models import Level, Role

    member = make_member(engine, role="instructor", level="intermediate", name="Tiago Costa",
                         email="lineup.tiago@novasbe.pt")
    with engine.connect() as conn:
        actor = db().get_actor(conn, member)
    assert actor.id == member
    assert actor.role is Role.INSTRUCTOR
    assert actor.level is Level.INTERMEDIATE
    assert (actor.full_name, actor.email) == ("Tiago Costa", "lineup.tiago@novasbe.pt")


def test_section8_get_actor_unknown_id_is_none(engine):
    with engine.connect() as conn:
        assert db().get_actor(conn, 12345) is None


def test_r10_7_lock_member_runs_on_sqlite(engine):
    member = make_member(engine)
    with engine.begin() as conn:
        db().lock_member(conn, member)


def test_section9_get_session_returns_a_view_with_end_time(engine, now):
    from lineup.models import Level, SessionStatus

    tiago = make_member(engine, role="instructor", name="Tiago Costa")
    start = now + timedelta(days=1, hours=1)
    sid = make_session(engine, tiago, start, duration_min=90, capacity=4)
    with engine.connect() as conn:
        view = db().get_session(conn, sid)
        missing = db().get_session(conn, 999)
    assert view.instructor_name == "Tiago Costa"
    assert view.ends_at == start + timedelta(minutes=90)
    assert (view.level, view.status, view.capacity, view.booked_count) == (
        Level.BEGINNER, SessionStatus.SCHEDULED, 4, 0)
    assert missing is None


def test_lu03_upcoming_sessions_next_14_days_scheduled_in_order(engine, now):
    tiago = make_member(engine, role="instructor")
    day = timedelta(days=1)
    make_session(engine, tiago, now - timedelta(hours=1))                     # already started
    make_session(engine, tiago, now)                                          # starts right now
    later = make_session(engine, tiago, now + 2 * day)
    sooner = make_session(engine, tiago, now + day)
    make_session(engine, tiago, now + day + timedelta(hours=3), status="called_off")
    last_day = make_session(engine, tiago, datetime(2026, 12, 4, 16, 0))     # today + 14
    make_session(engine, tiago, datetime(2026, 12, 5, 8, 0))                 # today + 15
    with engine.connect() as conn:
        ids = [s.id for s in db().upcoming_sessions(conn, now)]
    assert ids == [sooner, later, last_day]


# ---- Partial unique index on bookings ----


def test_r3_7_second_confirmed_booking_for_same_session_is_refused(engine, now):
    tiago = make_member(engine, role="instructor")
    ana = make_member(engine)
    give_credits(engine, ana, 2)
    sid = make_session(engine, tiago, now + timedelta(days=1))
    make_booking(engine, ana, sid)
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert(schema().bookings).values(
                session_id=sid, member_id=ana, status="confirmed",
            ))


def test_r3_7_cancelled_booking_then_new_confirmed_one_is_allowed(engine, now):
    s = schema()
    tiago = make_member(engine, role="instructor")
    ana = make_member(engine)
    give_credits(engine, ana, 2)
    sid = make_session(engine, tiago, now + timedelta(days=2))
    first = make_booking(engine, ana, sid)
    with engine.begin() as conn:
        conn.execute(update(s.bookings).where(s.bookings.c.id == first)
                     .values(status="cancelled", cancelled_at=now))
        conn.execute(update(s.surf_sessions).where(s.surf_sessions.c.id == sid)
                     .values(booked_count=s.surf_sessions.c.booked_count - 1))
    make_booking(engine, ana, sid)
    assert count(engine, s.bookings, s.bookings.c.session_id == sid) == 2


# ---- Factories ----


def test_section9_make_booking_takes_a_place_and_charges_one_credit(engine, now):
    s = schema()
    tiago = make_member(engine, role="instructor")
    ana = make_member(engine)
    give_credits(engine, ana, 3)
    sid = make_session(engine, tiago, now + timedelta(days=1))
    booking = make_booking(engine, ana, sid)
    with engine.connect() as conn:
        assert db().get_session(conn, sid).booked_count == 1
        rows = conn.execute(select(s.credit_ledger.c.delta, s.credit_ledger.c.kind)
                            .where(s.credit_ledger.c.ref == f"booking:{booking}")).all()
        assert db().ledger_balance(conn, ana) == 2
    assert [tuple(r) for r in rows] == [(-1, "booking")]


# ---- Invariants ----


def test_section9_invariants_hold_on_clean_data(engine, now):
    tiago = make_member(engine, role="instructor")
    ana = make_member(engine)
    give_credits(engine, ana, 1)
    make_booking(engine, ana, make_session(engine, tiago, now + timedelta(days=1)))
    with engine.connect() as conn:
        assert db().check_invariants(conn) == []


def test_section9_invariant_reports_a_booked_count_mismatch(raw_engine, now):
    s = schema()
    tiago = make_member(raw_engine, role="instructor")
    ana = make_member(raw_engine)
    give_credits(raw_engine, ana, 1)
    sid = make_session(raw_engine, tiago, now + timedelta(days=1))
    make_booking(raw_engine, ana, sid)
    with raw_engine.begin() as conn:
        conn.execute(update(s.surf_sessions).values(booked_count=0))
        problems = db().check_invariants(conn)
    assert any("booked_count" in p for p in problems)


def test_r10_7_invariant_reports_a_negative_balance(raw_engine):
    ana = make_member(raw_engine)
    with raw_engine.begin() as conn:
        conn.execute(insert(schema().credit_ledger).values(
            member_id=ana, delta=-1, kind="booking", ref="manual:1",
        ))
        problems = db().check_invariants(conn)
    assert any("negative" in p for p in problems)


def test_r8_invariant_reports_a_called_off_session_with_bookings(raw_engine, now):
    s = schema()
    tiago = make_member(raw_engine, role="instructor")
    ana = make_member(raw_engine)
    give_credits(raw_engine, ana, 1)
    sid = make_session(raw_engine, tiago, now + timedelta(days=1))
    make_booking(raw_engine, ana, sid)
    with raw_engine.begin() as conn:
        conn.execute(update(s.surf_sessions).values(status="called_off"))
        problems = db().check_invariants(conn)
    assert any("called off" in p for p in problems)


def test_r10_8_invariant_reports_a_booking_without_its_ledger_row(raw_engine, now):
    s = schema()
    tiago = make_member(raw_engine, role="instructor")
    ana = make_member(raw_engine)
    sid = make_session(raw_engine, tiago, now + timedelta(days=1))
    with raw_engine.begin() as conn:
        conn.execute(insert(s.bookings).values(session_id=sid, member_id=ana, status="confirmed"))
        conn.execute(update(s.surf_sessions).values(booked_count=1))
        problems = db().check_invariants(conn)
    assert any("ledger" in p for p in problems)


def test_r3_5_invariant_reports_overlapping_bookings(raw_engine, now):
    tiago = make_member(raw_engine, role="instructor")
    ines = make_member(raw_engine, role="instructor")
    ana = make_member(raw_engine)
    give_credits(raw_engine, ana, 2)
    start = now + timedelta(days=1)
    make_booking(raw_engine, ana, make_session(raw_engine, tiago, start, duration_min=90))
    make_booking(raw_engine, ana, make_session(raw_engine, ines, start + timedelta(minutes=60)))
    with raw_engine.connect() as conn:
        problems = db().check_invariants(conn)
    assert any("overlap" in p for p in problems)


def test_r3_5_back_to_back_bookings_are_not_an_overlap(engine, now):
    tiago = make_member(engine, role="instructor")
    ines = make_member(engine, role="instructor")
    ana = make_member(engine)
    give_credits(engine, ana, 2)
    start = now + timedelta(days=1)
    make_booking(engine, ana, make_session(engine, tiago, start, duration_min=90))
    make_booking(engine, ana, make_session(engine, ines, start + timedelta(minutes=90)))
    with engine.connect() as conn:
        assert db().check_invariants(conn) == []
