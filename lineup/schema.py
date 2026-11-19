"""The 12 tables of spec section 9, in SQLAlchemy Core.

This is the only place tables are defined. Datetimes are naive UTC, money
is integer cents, and the constraints repeat the rules so bad data is
refused by the database even if a service has a bug.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    text,
)

from lineup.config import CAPACITY_MAX, CAPACITY_MIN, DURATIONS
from lineup.models import (
    Attendance,
    BookingStatus,
    CallOffCategory,
    LedgerKind,
    Level,
    RequestStatus,
    Role,
    SessionStatus,
    WaitStatus,
)
from lineup.timeutil import utcnow

# Stable constraint names, so Postgres errors and future migrations can name them.
metadata = MetaData(naming_convention={
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
})


def _one_of(column: str, enum) -> CheckConstraint:
    # Values come from our own enums, never from user input.
    allowed = ", ".join(f"'{member.value}'" for member in enum)
    return CheckConstraint(f"{column} IN ({allowed})", name=f"{column}_allowed")


members = Table(
    "members", metadata,
    Column("id", Integer, primary_key=True),
    Column("auth_user_id", String(64), unique=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("full_name", String(60), nullable=False),
    Column("role", String(20), nullable=False, default=Role.STUDENT.value),
    Column("level", String(20), nullable=False, default=Level.BEGINNER.value),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    _one_of("role", Role),
    _one_of("level", Level),
    CheckConstraint("email = lower(email)", name="email_lower_case"),
)

surf_sessions = Table(
    "surf_sessions", metadata,
    Column("id", Integer, primary_key=True),
    Column("instructor_id", Integer, ForeignKey("members.id"), nullable=False),
    Column("starts_at", DateTime, nullable=False),
    Column("duration_min", Integer, nullable=False),
    Column("level", String(20), nullable=False),
    Column("capacity", Integer, nullable=False),
    Column("booked_count", Integer, nullable=False, default=0),
    Column("status", String(20), nullable=False, default=SessionStatus.SCHEDULED.value),
    Column("call_off_category", String(30)),
    Column("call_off_reason", String(200)),
    Column("called_off_at", DateTime),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    _one_of("level", Level),
    _one_of("status", SessionStatus),
    CheckConstraint(
        "call_off_category IS NULL OR call_off_category IN ("
        + ", ".join(f"'{c.value}'" for c in CallOffCategory) + ")",
        name="call_off_category_allowed",
    ),
    CheckConstraint(
        f"duration_min IN ({', '.join(str(d) for d in DURATIONS)})", name="duration_allowed"
    ),
    CheckConstraint(
        f"capacity BETWEEN {CAPACITY_MIN} AND {CAPACITY_MAX}", name="capacity_range"
    ),
    CheckConstraint("booked_count >= 0 AND booked_count <= capacity", name="booked_within_capacity"),
    Index("ix_surf_sessions_starts_at", "starts_at"),
    Index("ix_surf_sessions_instructor_id", "instructor_id"),
)

bookings = Table(
    "bookings", metadata,
    Column("id", Integer, primary_key=True),
    Column("session_id", Integer, ForeignKey("surf_sessions.id"), nullable=False),
    Column("member_id", Integer, ForeignKey("members.id"), nullable=False),
    Column("status", String(20), nullable=False, default=BookingStatus.CONFIRMED.value),
    Column("attendance", String(20)),
    Column("refunded", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("cancelled_at", DateTime),
    _one_of("status", BookingStatus),
    CheckConstraint(
        "attendance IS NULL OR attendance IN ("
        + ", ".join(f"'{a.value}'" for a in Attendance) + ")",
        name="attendance_allowed",
    ),
    Index("ix_bookings_member_id", "member_id"),
    # R3.7: one confirmed booking per student per session.
    Index(
        "uq_bookings_one_confirmed", "session_id", "member_id", unique=True,
        sqlite_where=text("status = 'confirmed'"),
        postgresql_where=text("status = 'confirmed'"),
    ),
)

waitlist_entries = Table(
    "waitlist_entries", metadata,
    Column("id", Integer, primary_key=True),
    Column("session_id", Integer, ForeignKey("surf_sessions.id"), nullable=False),
    Column("member_id", Integer, ForeignKey("members.id"), nullable=False),
    Column("status", String(20), nullable=False, default=WaitStatus.WAITING.value),
    Column("reason", String(200)),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("updated_at", DateTime, nullable=False, default=utcnow),
    _one_of("status", WaitStatus),
    Index("ix_waitlist_entries_member_id", "member_id"),
    # R4.1: one waiting entry per student per session.
    Index(
        "uq_waitlist_entries_one_waiting", "session_id", "member_id", unique=True,
        sqlite_where=text("status = 'waiting'"),
        postgresql_where=text("status = 'waiting'"),
    ),
)

credit_packs = Table(
    "credit_packs", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(40), nullable=False),
    Column("credits", Integer, nullable=False),
    Column("price_cents", Integer, nullable=False),
    Column("active", Boolean, nullable=False, default=True),
    CheckConstraint("credits > 0", name="credits_positive"),
    CheckConstraint("price_cents >= 0", name="price_not_negative"),
)

credit_requests = Table(
    "credit_requests", metadata,
    Column("id", Integer, primary_key=True),
    Column("member_id", Integer, ForeignKey("members.id"), nullable=False),
    Column("pack_id", Integer, ForeignKey("credit_packs.id"), nullable=False),
    Column("payment_ref", String(40), nullable=False),
    Column("status", String(20), nullable=False, default=RequestStatus.PENDING.value),
    Column("decided_by", Integer, ForeignKey("members.id")),
    Column("decided_at", DateTime),
    Column("decision_note", String(200)),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    _one_of("status", RequestStatus),
    Index("ix_credit_requests_member_id", "member_id"),
    # R10.2: at most one pending request per student.
    Index(
        "uq_credit_requests_one_pending", "member_id", unique=True,
        sqlite_where=text("status = 'pending'"),
        postgresql_where=text("status = 'pending'"),
    ),
)

credit_ledger = Table(
    "credit_ledger", metadata,
    Column("id", Integer, primary_key=True),
    Column("member_id", Integer, ForeignKey("members.id"), nullable=False),
    Column("delta", Integer, nullable=False),
    Column("kind", String(20), nullable=False),
    # R10.8: the unique reference is what stops a double charge or refund.
    Column("ref", String(60), nullable=False, unique=True),
    Column("note", String(200)),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    _one_of("kind", LedgerKind),
    CheckConstraint("delta <> 0", name="delta_not_zero"),
    Index("ix_credit_ledger_member_id", "member_id"),
)

notifications = Table(
    "notifications", metadata,
    Column("id", Integer, primary_key=True),
    Column("member_id", Integer, ForeignKey("members.id"), nullable=False),
    Column("kind", String(40), nullable=False),
    Column("message", String(300), nullable=False),
    Column("created_at", DateTime, nullable=False, default=utcnow),
    Column("read_at", DateTime),
    Index("ix_notifications_member_id", "member_id"),
)

forecast_hours = Table(
    "forecast_hours", metadata,
    Column("hour_utc", DateTime, primary_key=True),
    Column("wave_height_m", Float),
    Column("wind_speed_kmh", Float),
    Column("fetched_at", DateTime, nullable=False),
)

forecast_days = Table(
    "forecast_days", metadata,
    Column("day", Date, primary_key=True),
    Column("sunset_utc", DateTime),
    Column("fetched_at", DateTime, nullable=False),
)

condition_thresholds = Table(
    "condition_thresholds", metadata,
    Column("level", String(20), primary_key=True),
    Column("go_wave_m", Float, nullable=False),
    Column("go_wind_kmh", Float, nullable=False),
    Column("marginal_wave_m", Float, nullable=False),
    Column("marginal_wind_kmh", Float, nullable=False),
    Column("updated_by", Integer, ForeignKey("members.id")),
    Column("updated_at", DateTime),
    _one_of("level", Level),
)

app_settings = Table(
    "app_settings", metadata,
    Column("key", String(60), primary_key=True),
    Column("value", Text),
    Column("updated_at", DateTime, nullable=False, default=utcnow),
)
