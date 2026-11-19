"""Acceptance scenario A16: data survives a restart of the app."""

from datetime import datetime

from conftest import give_credits, make_booking, make_member, make_session


def open_engine(path):
    from lineup import db

    eng = db.make_engine(f"sqlite:///{path.as_posix()}")
    db.init_db(eng)
    return eng


def test_a16_member_survives_an_engine_restart(tmp_path):
    from lineup import db

    path = tmp_path / "lineup.db"
    first = open_engine(path)
    member = make_member(first, name="Ana Martins", email="lineup.ana@novasbe.pt")
    first.dispose()

    second = open_engine(path)
    try:
        with second.connect() as conn:
            actor = db.get_actor(conn, member)
            assert db.check_invariants(conn) == []
    finally:
        second.dispose()
    assert (actor.full_name, actor.email) == ("Ana Martins", "lineup.ana@novasbe.pt")


def test_a16_booking_and_balance_survive_an_engine_restart(tmp_path):
    from lineup import db

    path = tmp_path / "lineup.db"
    first = open_engine(path)
    tiago = make_member(first, role="instructor")
    ana = make_member(first)
    give_credits(first, ana, 3)
    sid = make_session(first, tiago, datetime(2026, 11, 21, 10, 0))
    make_booking(first, ana, sid)
    first.dispose()

    second = open_engine(path)
    try:
        with second.connect() as conn:
            assert db.get_session(conn, sid).booked_count == 1
            assert db.ledger_balance(conn, ana) == 2
            assert db.check_invariants(conn) == []
    finally:
        second.dispose()
