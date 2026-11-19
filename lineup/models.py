"""Shared result type, error codes, enums and plain data classes.

Every service returns a Result; screens and tests read its code, never its
wording, so the wording can change in one place (spec section 11).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


class Code(StrEnum):
    """Why an action was refused.

    Rules: section 5 (refusal codes).
    """

    FORBIDDEN = "forbidden"
    INVALID = "invalid"
    NOT_FOUND = "not_found"
    CLOSED = "closed"
    NOT_YET = "not_yet"
    NO_CREDITS = "no_credits"
    CLASH = "clash"
    LEVEL = "level"
    DUPLICATE = "duplicate"
    FULL = "full"
    NOT_FULL = "not_full"
    ALREADY_DONE = "already_done"


@dataclass(frozen=True)
class Result:
    """Outcome of a service call: ok with a message, or refused with a code.

    Rules: section 8 (Result convention).
    """

    ok: bool
    message: str
    code: Code | None = None
    data: Any = None

    @classmethod
    def success(cls, message: str, data: Any = None) -> Result:
        """Build a successful result with no code.

        Rules: section 8.
        """
        return cls(ok=True, message=message, code=None, data=data)

    @classmethod
    def fail(cls, code: Code, message: str, data: Any = None) -> Result:
        """Build a refused result carrying the reason code.

        Rules: section 8.
        """
        return cls(ok=False, message=message, code=code, data=data)


MESSAGES: dict[Code, str] = {
    Code.FORBIDDEN: "You don't have permission to do that.",
    Code.INVALID: "{field}: {problem}. Allowed: {allowed}.",
    Code.NOT_FOUND: "That item no longer exists. Refresh the page.",
    Code.CLOSED: "Too late: {what} closed at {time}.",
    Code.NOT_YET: "This opens when the session starts at {time}.",
    Code.NO_CREDITS: "You have no credits left. Request a pack on the Credits page.",
    Code.CLASH: "You already have a session at that time ({time}).",
    Code.LEVEL: (
        "Intermediate sessions need 3 attended Beginner sessions "
        "or an Intermediate level. You have {n}."
    ),
    Code.DUPLICATE: "You're already booked or waiting here.",
    Code.FULL: "This session just filled up. Join the waitlist to get the next free place.",
    Code.NOT_FULL: "There are places left, so book directly.",
    Code.ALREADY_DONE: "Nothing changed: this was already done.",
}


def fill(code: Code, **values: Any) -> str:
    """Return the catalogue message for a code with its placeholders filled.

    A missing placeholder raises KeyError on purpose, so a half-filled
    message fails a test instead of reaching a user.

    Rules: section 11 (message catalogue).
    """
    return MESSAGES[code].format(**values)


class Role(StrEnum):
    """Member role.

    Rules: section 3.
    """

    STUDENT = "student"
    INSTRUCTOR = "instructor"
    ADMIN = "admin"


class Level(StrEnum):
    """Member and session level.

    Rules: R2.5, R3.6.
    """

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"


class SessionStatus(StrEnum):
    """Stored session status; running and finished come from the clock.

    Rules: section 9, R8.
    """

    SCHEDULED = "scheduled"
    CALLED_OFF = "called_off"


class BookingStatus(StrEnum):
    """Booking status.

    Rules: section 9, R5, R8.3.
    """

    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    CALLED_OFF = "called_off"


class Attendance(StrEnum):
    """Attendance mark on a confirmed booking.

    Rules: R9.2.
    """

    ATTENDED = "attended"
    NO_SHOW = "no_show"


class WaitStatus(StrEnum):
    """Waitlist entry status.

    Rules: section 9, R4, R8.4.
    """

    WAITING = "waiting"
    PROMOTED = "promoted"
    LEFT = "left"
    REMOVED = "removed"
    CLEARED = "cleared"


class RequestStatus(StrEnum):
    """Credit request status.

    Rules: R10.2-R10.6.
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class LedgerKind(StrEnum):
    """Kind of credit ledger row.

    Rules: R10.7, R10.8.
    """

    PURCHASE = "purchase"
    BOOKING = "booking"
    REFUND = "refund"


class CallOffCategory(StrEnum):
    """Reason category for calling a session off.

    Rules: R8.2.
    """

    CONDITIONS = "conditions"
    INSTRUCTOR_UNAVAILABLE = "instructor_unavailable"
    OTHER = "other"


class Label(StrEnum):
    """Conditions label shown on a session.

    Rules: R6.3, R6.4.
    """

    GO = "go"
    MARGINAL = "marginal"
    NO_GO = "no_go"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Actor:
    """The member performing an action, read fresh from the database.

    Rules: section 3, section 8 (Actor convention).
    """

    id: int
    email: str
    full_name: str
    role: Role
    level: Level


@dataclass(frozen=True)
class SessionView:
    """A surf session as screens and services read it.

    Rules: section 9.
    """

    id: int
    instructor_id: int
    instructor_name: str
    starts_at: datetime
    duration_min: int
    level: Level
    capacity: int
    booked_count: int
    status: SessionStatus

    @property
    def ends_at(self) -> datetime:
        """Start plus duration, in naive UTC like starts_at.

        Rules: R2.3, R6.1.
        """
        return self.starts_at + timedelta(minutes=self.duration_min)


@dataclass(frozen=True)
class Condition:
    """Conditions label for one session, with the numbers behind it.

    Rules: R6.2-R6.4.
    """

    label: Label
    wave_m: float | None
    wind_kmh: float | None
    note: str
