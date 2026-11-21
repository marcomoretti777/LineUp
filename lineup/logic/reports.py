"""Pure rules for attendance and CSV exports. Owner: Member 4 (Credits and reports lane).

No database, screen or clock access: "now" and every loaded value arrive as
parameters, so each rule is tested without fixtures.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from lineup.models import Code, Result, SessionStatus, fill
from lineup.timeutil import fmt_time

# A spreadsheet treats a cell starting with one of these as a formula.
_FORMULA_STARTS = ("=", "+", "-", "@")


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
