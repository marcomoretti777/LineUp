"""Session actions. Owner: Member 3 (Sessions and forecast lane).

The lead created this stub in F03 so other lanes can call the contract
function now; Member 3 replaces the body in their own task.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Engine

from lineup.models import Code, Result


def call_off(engine: Engine, actor_id: int, session_id: int, category: str, reason: str,
             now: datetime | None = None) -> Result:
    """Call a session off for everyone, refunding and notifying them.

    Stub owned by Member 3: refuses until the Sessions lane builds it.

    Rules: R8.1-R8.5.
    """
    return Result.fail(Code.NOT_FOUND, "Call-off is not built yet")
