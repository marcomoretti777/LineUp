"""Pure rules for attendance and CSV exports. Owner: Member 4 (Credits and reports lane).

No database, screen or clock access: "now" and every loaded value arrive as
parameters, so each rule is tested without fixtures.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from typing import Any

from lineup.models import Attendance, Code, Level, Result, SessionStatus, fill
from lineup.timeutil import fmt_time, local_date

# A spreadsheet treats a cell starting with one of these as a formula.
_FORMULA_STARTS = ("=", "+", "-", "@")

MAX_PERIOD_DAYS = 92
_PERIOD_ALLOWED = f"start on or before end, at most {MAX_PERIOD_DAYS} days"


def csv_safe(value: Any) -> Any:
    """Return a CSV cell that a spreadsheet can never run as a formula.

    Text starting with =, +, - or @ gets a leading apostrophe; None becomes
    an empty cell; numbers and other text pass through unchanged.

    Rules: R12.7.
    """
    if value is None:
        return ""
    if isinstance(value, str) and value.startswith(_FORMULA_STARTS):
        return "'" + value
    return value


def to_csv(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    """Write a header and rows as CSV text, passing every cell through csv_safe.

    Rules: R12.7.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([csv_safe(cell) for cell in header])
    for row in rows:
        writer.writerow([csv_safe(cell) for cell in row])
    return buffer.getvalue()


def check_can_mark_attendance(
    *,
    session_status: SessionStatus | str,
    starts_at: datetime,
    now: datetime,
    called_off_at: datetime | None = None,
) -> Result | None:
    """Return the refusal for marking attendance at `now`, or None when it is open.

    A called-off session is closed for good, so that check comes before the
    start time.

    Rules: R9.1.
    """
    if SessionStatus(session_status) == SessionStatus.CALLED_OFF:
        when = called_off_at or starts_at
        return Result.fail(Code.CLOSED, fill(Code.CLOSED, what="attendance", time=fmt_time(when)))
    if now < starts_at:
        return Result.fail(Code.NOT_YET, fill(Code.NOT_YET, time=fmt_time(starts_at)))
    return None


def validate_period(start: date, end: date) -> Result | None:
    """Return INVALID for a report period that runs backwards or past 92 days, else None.

    Both days count, so 1 Nov to 30 Nov is 30 days.

    Rules: R12.1.
    """
    if end < start:
        problem = "the end date is before the start date"
    elif (end - start).days + 1 > MAX_PERIOD_DAYS:
        problem = f"{(end - start).days + 1} days is too long"
    else:
        return None
    return Result.fail(Code.INVALID, fill(
        Code.INVALID, field="Period", problem=problem, allowed=_PERIOD_ALLOWED,
    ))


def fill_rate(sessions: Iterable[Any]) -> float | None:
    """Return confirmed places ÷ capacity over sessions run, or None when there are none.

    Each item has booked_count and capacity.

    Rules: R12.3.
    """
    rows = list(sessions)
    capacity = sum(s.capacity for s in rows)
    if capacity == 0:
        return None
    return sum(s.booked_count for s in rows) / capacity


def fill_rate_by_level(sessions: Iterable[Any]) -> dict[str, float]:
    """Return the fill rate per session level, leaving out levels with no sessions run.

    Each item has level, booked_count and capacity.

    Rules: R12.3.
    """
    rows = list(sessions)
    rates = {}
    for level in Level:
        rate = fill_rate(s for s in rows if s.level == level.value)
        if rate is not None:
            rates[level.value] = rate
    return rates


def no_show_rate(marks: Iterable[str | None]) -> float | None:
    """Return no-shows ÷ (attended + no-shows), or None when nothing is marked.

    Unmarked bookings (None) are ignored.

    Rules: R12.4.
    """
    counts = Counter(m for m in marks if m is not None)
    marked = counts[Attendance.ATTENDED.value] + counts[Attendance.NO_SHOW.value]
    if marked == 0:
        return None
    return counts[Attendance.NO_SHOW.value] / marked


def credits_sold(approved: Iterable[Any]) -> int:
    """Return the credits in the approved requests; each item has credits.

    Rules: R12.5.
    """
    return sum(r.credits for r in approved)


def revenue_cents(approved: Iterable[Any]) -> int:
    """Return the money in the approved requests, in integer cents; each item has price_cents.

    Rules: R12.5.
    """
    return sum(r.price_cents for r in approved)


def calloffs_by_category(categories: Iterable[str | None]) -> dict[str, int]:
    """Count call-offs per category, listing only categories that occur.

    Rules: R12.6.
    """
    return dict(Counter(c for c in categories if c is not None))


def calloffs_total(calloffs: dict[str, int]) -> int:
    """Return the number of call-offs across all categories.

    Rules: R12.6.
    """
    return sum(calloffs.values())

def bookings_per_week(session_starts: Iterable[datetime]) -> dict[str, int]:
    """Count bookings by the ISO week of their session's Lisbon start date, oldest week first.

    One item per confirmed booking; keys look like "2026-W47".

    Rules: R12.3 (bookings chart).
    """
    weeks = Counter()
    for start in session_starts:
        year, week, _ = local_date(start).isocalendar()
        weeks[f"{year}-W{week:02d}"] += 1
    return dict(sorted(weeks.items()))


def eur_text(cents: int) -> str:
    """Format integer cents as a plain euro amount for CSV, such as "65.00".

    Rules: R10.1, R12.5.
    """
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"
