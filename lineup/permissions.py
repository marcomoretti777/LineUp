"""The permission matrix of spec section 3, written as data.

Services call require() after loading the actor from the database, so a
hidden button is never the check and a demoted member loses rights at once.
"""

from __future__ import annotations

from enum import StrEnum

from lineup.models import MESSAGES, Actor, Code, Result, Role


class Action(StrEnum):
    """Every action a service can check.

    Rules: section 3.
    """

    VIEW_SESSIONS = "view_sessions"
    BOOK = "book"
    CANCEL_BOOKING = "cancel_booking"
    JOIN_WAITLIST = "join_waitlist"
    LEAVE_WAITLIST = "leave_waitlist"
    REQUEST_CREDITS = "request_credits"
    WITHDRAW_REQUEST = "withdraw_request"
    VIEW_STATEMENT = "view_statement"
    READ_NOTIFICATIONS = "read_notifications"
    MANAGE_OWN_SESSIONS = "manage_own_sessions"
    VIEW_ROSTER = "view_roster"
    MARK_ATTENDANCE = "mark_attendance"
    EXPORT_ROSTER = "export_roster"
    CALL_OFF = "call_off"
    DECIDE_CREDITS = "decide_credits"
    MANAGE_MEMBERS = "manage_members"
    EDIT_SETTINGS = "edit_settings"
    VIEW_REPORTS = "view_reports"


ALL = "all"
OWN = "own"
NONE = "none"

_S, _I, _A = Role.STUDENT, Role.INSTRUCTOR, Role.ADMIN

# One row per action, read like the table in spec section 3.
MATRIX: dict[Action, dict[Role, str]] = {
    Action.VIEW_SESSIONS:       {_S: ALL,  _I: ALL,  _A: ALL},
    Action.BOOK:                {_S: OWN,  _I: NONE, _A: NONE},
    Action.CANCEL_BOOKING:      {_S: OWN,  _I: NONE, _A: NONE},
    Action.JOIN_WAITLIST:       {_S: OWN,  _I: NONE, _A: NONE},
    Action.LEAVE_WAITLIST:      {_S: OWN,  _I: NONE, _A: NONE},
    Action.REQUEST_CREDITS:     {_S: OWN,  _I: NONE, _A: NONE},
    Action.WITHDRAW_REQUEST:    {_S: OWN,  _I: NONE, _A: NONE},
    Action.VIEW_STATEMENT:      {_S: OWN,  _I: NONE, _A: ALL},
    Action.READ_NOTIFICATIONS:  {_S: OWN,  _I: OWN,  _A: OWN},
    Action.MANAGE_OWN_SESSIONS: {_S: NONE, _I: OWN,  _A: NONE},
    Action.VIEW_ROSTER:         {_S: NONE, _I: OWN,  _A: ALL},
    Action.MARK_ATTENDANCE:     {_S: NONE, _I: OWN,  _A: ALL},
    Action.EXPORT_ROSTER:       {_S: NONE, _I: OWN,  _A: ALL},
    Action.CALL_OFF:            {_S: NONE, _I: OWN,  _A: ALL},
    Action.DECIDE_CREDITS:      {_S: NONE, _I: NONE, _A: ALL},
    Action.MANAGE_MEMBERS:      {_S: NONE, _I: NONE, _A: ALL},
    Action.EDIT_SETTINGS:       {_S: NONE, _I: NONE, _A: ALL},
    Action.VIEW_REPORTS:        {_S: NONE, _I: NONE, _A: ALL},
}


def _forbidden() -> Result:
    return Result.fail(Code.FORBIDDEN, MESSAGES[Code.FORBIDDEN])


def require(actor: Actor | None, action: Action, owner_id: int | None = None) -> Result | None:
    """Return None if the actor may do the action, else a FORBIDDEN Result.

    Ownership rule (fail closed): for an "own" cell, owner_id must equal
    actor.id. A missing owner_id is refused. When the action creates a
    record for the actor (book, join a waitlist, request credits, create a
    session) or reads the actor's own data (notifications, statement), the
    service passes owner_id=actor.id. A missing actor is always refused.

    Rules: section 3, R1.5, R5.1, R8.1, R10.5, R11.3, R12.8.
    """
    if actor is None:
        return _forbidden()
    rule = MATRIX.get(action, {}).get(actor.role, NONE)
    if rule == ALL:
        return None
    if rule == OWN and owner_id is not None and owner_id == actor.id:
        return None
    return _forbidden()
