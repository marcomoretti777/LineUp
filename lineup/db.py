"""Engine, setup and the queries every lane shares.

All functions except make_engine and init_db take an open connection, so a
service runs everything it does inside one `with engine.begin() as conn:`
transaction (spec section 8).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from pathlib import Path

from sqlalchemy import (
    Connection,
    Engine,
    create_engine,
    event,
    func,
    insert,
    select,
)
from sqlalchemy.pool import StaticPool

from lineup import schema
from lineup.config import CREDIT_PACKS, DEFAULT_THRESHOLDS, MAX_DAYS_AHEAD
from lineup.models import (
    Actor,
    BookingStatus,
    LedgerKind,
    Level,
    Role,
    SessionStatus,
    SessionView,
    WaitStatus,
)
from lineup.timeutil import from_local, local_date

DEFAULT_SQLITE_PATH = Path("data") / "lineup.db"
NOTIFICATION_MAX = 300


def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
    # SQLite ignores foreign keys unless each connection turns them on.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def make_engine(url: str | None = None) -> Engine:
    """Create the database engine for a URL, or the local SQLite file if none.

    "sqlite://" gives an in-memory database shared through one connection
    (tests). Postgres connections are checked before use, because the
    Supabase pooler drops idle ones.

    Rules: section 8, section 14 (settings the app reads).
    """
    if not url:
        DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"

    if url.startswith("sqlite"):
        options: dict = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            options["poolclass"] = StaticPool
        engine = create_engine(url, **options)
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
        return engine

    return create_engine(url, pool_pre_ping=True)


def rls_statements(dialect_name: str) -> list[str]:
    """Return the statements that turn on Row Level Security for every table.

    Only Postgres has it. With RLS on and no policies, Supabase's public
    REST API sees no rows, while the app connects as the tables' owner.

    Rules: section 12 (database exposure).
    """
    if dialect_name != "postgresql":
        return []
    # Table names come from schema.py, never from input.
    return [
        f"ALTER TABLE {table.name} ENABLE ROW LEVEL SECURITY"
        for table in schema.metadata.sorted_tables
    ]


def init_db(engine: Engine) -> None:
    """Create missing tables, add default packs and thresholds, enable RLS.

    Safe to run on every start: existing tables and rows are left alone.

    Rules: section 9, R10.1, R6 (default thresholds), section 12.
    """
    schema.metadata.create_all(engine)
    with engine.begin() as conn:
        if _count(conn, schema.credit_packs) == 0:
            conn.execute(insert(schema.credit_packs), [
                {"name": name, "credits": credits, "price_cents": price}
                for name, credits, price in CREDIT_PACKS
            ])
        if _count(conn, schema.condition_thresholds) == 0:
            conn.execute(insert(schema.condition_thresholds), [
                {
                    "level": level,
                    "go_wave_m": go_wave,
                    "go_wind_kmh": go_wind,
                    "marginal_wave_m": marginal_wave,
                    "marginal_wind_kmh": marginal_wind,
                }
                for level, (go_wave, go_wind, marginal_wave, marginal_wind)
                in DEFAULT_THRESHOLDS.items()
            ])
        for statement in rls_statements(engine.dialect.name):
            conn.exec_driver_sql(statement)


def _count(conn: Connection, table, *where) -> int:
    return conn.execute(select(func.count()).select_from(table).where(*where)).scalar_one()


def get_actor(conn: Connection, member_id: int) -> Actor | None:
    """Load a member as an Actor, reading the role fresh from the database.

    Rules: section 3, section 8 (Actor convention), R1.5.
    """
    m = schema.members
    row = conn.execute(
        select(m.c.id, m.c.email, m.c.full_name, m.c.role, m.c.level).where(m.c.id == member_id)
    ).first()
    if row is None:
        return None
    return Actor(
        id=row.id, email=row.email, full_name=row.full_name,
        role=Role(row.role), level=Level(row.level),
    )


def lock_member(conn: Connection, member_id: int) -> None:
    """Lock a member's row until the transaction ends (SELECT ... FOR UPDATE).

    Services call it before charging credits, so two requests from the same
    member cannot both spend the last credit. SQLite ignores FOR UPDATE and
    serialises writes on its own.

    Rules: R10.7, section 8 (credits under concurrency).
    """
    m = schema.members
    conn.execute(select(m.c.id).where(m.c.id == member_id).with_for_update())


def ledger_add(conn: Connection, member_id: int, delta: int, kind: str, ref: str,
               note: str | None = None) -> bool:
    """Write one ledger row; return False and write nothing if ref exists.

    The check runs before the insert, because a failed insert would abort
    the caller's whole transaction on Postgres. The unique constraint on
    ref stays as the last line of defence.

    Rules: R10.6, R10.8.
    """
    ledger = schema.credit_ledger
    if conn.execute(select(ledger.c.id).where(ledger.c.ref == ref)).first() is not None:
        return False
    conn.execute(insert(ledger).values(
        member_id=member_id, delta=delta, kind=LedgerKind(kind).value, ref=ref, note=note,
    ))
    return True


def ledger_balance(conn: Connection, member_id: int) -> int:
    """Return a member's credit balance: the sum of their ledger rows.

    Rules: R10.7.
    """
    ledger = schema.credit_ledger
    return conn.execute(
        select(func.coalesce(func.sum(ledger.c.delta), 0)).where(ledger.c.member_id == member_id)
    ).scalar_one()


def notify(conn: Connection, member_id: int, kind: str, message: str) -> None:
    """Add a notification in the caller's transaction.

    Messages longer than 300 characters are shortened with an ellipsis
    rather than failing the action that sent them.

    Rules: R11.1, R11.2, section 9 (notifications).
    """
    message = message.strip()
    if len(message) > NOTIFICATION_MAX:
        message = message[: NOTIFICATION_MAX - 1] + "…"
    conn.execute(insert(schema.notifications).values(
        member_id=member_id, kind=kind, message=message,
    ))


def unread_count(conn: Connection, member_id: int) -> int:
    """Return how many of a member's notifications are unread.

    Rules: R11, section 11 (sidebar).
    """
    n = schema.notifications
    return _count(conn, n, n.c.member_id == member_id, n.c.read_at.is_(None))


def _session_query():
    s, m = schema.surf_sessions, schema.members
    return select(
        s.c.id, s.c.instructor_id, m.c.full_name.label("instructor_name"), s.c.starts_at,
        s.c.duration_min, s.c.level, s.c.capacity, s.c.booked_count, s.c.status,
    ).join(m, m.c.id == s.c.instructor_id)


def _to_view(row) -> SessionView:
    return SessionView(
        id=row.id, instructor_id=row.instructor_id, instructor_name=row.instructor_name,
        starts_at=row.starts_at, duration_min=row.duration_min, level=Level(row.level),
        capacity=row.capacity, booked_count=row.booked_count, status=SessionStatus(row.status),
    )


def get_session(conn: Connection, session_id: int) -> SessionView | None:
    """Load one surf session with its instructor's name, or None.

    Rules: section 9.
    """
    row = conn.execute(_session_query().where(schema.surf_sessions.c.id == session_id)).first()
    return _to_view(row) if row else None


def upcoming_sessions(conn: Connection, now: datetime, days: int = MAX_DAYS_AHEAD) -> list[SessionView]:
    """Scheduled sessions starting after now, up to Lisbon today + days, by start.

    The limit is a Lisbon date, like R2.2, so a session late on the last
    day is still listed.

    Rules: LU03, R2.2.
    """
    s = schema.surf_sessions
    end = from_local(local_date(now) + timedelta(days=days + 1), time(0, 0))
    rows = conn.execute(
        _session_query()
        .where(s.c.status == SessionStatus.SCHEDULED.value, s.c.starts_at > now, s.c.starts_at < end)
        .order_by(s.c.starts_at, s.c.id)
    ).all()
    return [_to_view(row) for row in rows]


def check_invariants(conn: Connection) -> list[str]:
    """List every broken data invariant of spec section 9; empty means healthy.

    Rules: section 9 (invariants 1-5), R3.5, R10.7, R10.8.
    """
    problems: list[str] = []
    s, b, w = schema.surf_sessions, schema.bookings, schema.waitlist_entries
    ledger = schema.credit_ledger
    confirmed = BookingStatus.CONFIRMED.value

    # 1. booked_count equals the confirmed bookings.
    counts = (
        select(b.c.session_id, func.count().label("n"))
        .where(b.c.status == confirmed).group_by(b.c.session_id).subquery()
    )
    for row in conn.execute(
        select(s.c.id, s.c.booked_count, func.coalesce(counts.c.n, 0).label("n"))
        .outerjoin(counts, counts.c.session_id == s.c.id)
    ):
        if row.booked_count != row.n:
            problems.append(
                f"session {row.id}: booked_count {row.booked_count} "
                f"but {row.n} confirmed bookings"
            )

    # 2. No negative balance.
    for row in conn.execute(
        select(ledger.c.member_id, func.sum(ledger.c.delta).label("balance"))
        .group_by(ledger.c.member_id).having(func.sum(ledger.c.delta) < 0)
    ):
        problems.append(f"member {row.member_id}: balance {row.balance} is negative")

    # 3. A called-off session has no confirmed bookings and no waiting entries.
    called_off = select(s.c.id).where(s.c.status == SessionStatus.CALLED_OFF.value)
    for session_id in conn.execute(called_off).scalars():
        booked = _count(conn, b, b.c.session_id == session_id, b.c.status == confirmed)
        waiting = _count(conn, w, w.c.session_id == session_id,
                         w.c.status == WaitStatus.WAITING.value)
        if booked or waiting:
            problems.append(
                f"session {session_id}: called off but has {booked} confirmed "
                f"bookings and {waiting} waiting entries"
            )

    # 4. One booking:<id> row per booking, at most one refund:<id>, matching `refunded`.
    refs = Counter(conn.execute(select(ledger.c.ref)).scalars())
    for row in conn.execute(select(b.c.id, b.c.refunded)):
        charges, refunds = refs[f"booking:{row.id}"], refs[f"refund:{row.id}"]
        if charges != 1:
            problems.append(f"booking {row.id}: {charges} booking ledger rows, expected 1")
        if refunds > 1:
            problems.append(f"booking {row.id}: {refunds} refund ledger rows, expected at most 1")
        if bool(row.refunded) != (refunds == 1):
            problems.append(
                f"booking {row.id}: refunded is {bool(row.refunded)} "
                f"but it has {refunds} refund ledger rows"
            )

    # 5. No student has two overlapping confirmed bookings; back-to-back is fine.
    by_member: dict[int, list] = defaultdict(list)
    for row in conn.execute(
        select(b.c.id, b.c.member_id, s.c.starts_at, s.c.duration_min)
        .join(s, s.c.id == b.c.session_id).where(b.c.status == confirmed)
        .order_by(b.c.member_id, s.c.starts_at)
    ):
        by_member[row.member_id].append(row)
    for member_id, rows in by_member.items():
        # Compare with the booking that ends latest so far, not just the
        # previous one: a long booking can overlap several later ones.
        latest = None
        for row in rows:
            ends = row.starts_at + timedelta(minutes=row.duration_min)
            if latest is not None and row.starts_at < latest[1]:
                problems.append(
                    f"member {member_id}: bookings {latest[0]} and {row.id} overlap"
                )
            if latest is None or ends > latest[1]:
                latest = (row.id, ends)

    return problems
