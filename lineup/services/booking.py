"""Booking actions. Owner: Member 2 (Booking lane).

The lead created this stub in F03 so other lanes can call the contract
function now; Member 2 replaces the body in their own task.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection


def promote_waitlist(conn: Connection, session_id: int, now: datetime) -> list[int]:
    """Offer freed places to waiting students in join order; return promoted ids.

    Stub owned by Member 2: promotes nobody until the Booking lane builds it.

    Rules: R4.3, R4.4, R2.10, R5.3.
    """
    return []
