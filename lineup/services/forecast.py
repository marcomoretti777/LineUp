"""Forecast actions. Owner: Member 3 (Sessions and forecast lane).

The lead created these stubs in F03 so other lanes can call the contract
functions now; Member 3 replaces the bodies in their own tasks.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import Engine

from lineup.models import Condition, Label, SessionView


def conditions_for_sessions(engine: Engine, sessions: Iterable[SessionView],
                            now: datetime | None = None) -> dict[int, Condition]:
    """Return the conditions label for each session, keyed by session id.

    Stub owned by Member 3: every session is Unknown until the forecast is
    connected, which never blocks booking (R6.5).

    Rules: R6.1-R6.5, R7.
    """
    return {
        session.id: Condition(Label.UNKNOWN, None, None, "Forecast not connected yet")
        for session in sessions
    }


def sunset_for(engine: Engine, day: date) -> datetime | None:
    """Return the saved sunset time (naive UTC) for a Lisbon date, or None.

    Stub owned by Member 3: no sunset data yet, so R2.7 falls back to 17:00.

    Rules: R2.7.
    """
    return None
