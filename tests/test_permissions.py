"""Tests for the permission matrix of spec section 3.

Cases are parametrised by name so the file collects before the feature
exists; modules are imported inside each test.
"""

import importlib

import pytest

ALL, OWN, NONE = "all", "own", "none"

# Spec section 3, one row per Action: (student, instructor, admin).
MATRIX = {
    "VIEW_SESSIONS": (ALL, ALL, ALL),
    "BOOK": (OWN, NONE, NONE),
    "CANCEL_BOOKING": (OWN, NONE, NONE),
    "JOIN_WAITLIST": (OWN, NONE, NONE),
    "LEAVE_WAITLIST": (OWN, NONE, NONE),
    "REQUEST_CREDITS": (OWN, NONE, NONE),
    "WITHDRAW_REQUEST": (OWN, NONE, NONE),
    "VIEW_STATEMENT": (OWN, NONE, ALL),
    "READ_NOTIFICATIONS": (OWN, OWN, OWN),
    "MANAGE_OWN_SESSIONS": (NONE, OWN, NONE),
    "VIEW_ROSTER": (NONE, OWN, ALL),
    "MARK_ATTENDANCE": (NONE, OWN, ALL),
    "EXPORT_ROSTER": (NONE, OWN, ALL),
    "CALL_OFF": (NONE, OWN, ALL),
    "DECIDE_CREDITS": (NONE, NONE, ALL),
    "MANAGE_MEMBERS": (NONE, NONE, ALL),
    "EDIT_SETTINGS": (NONE, NONE, ALL),
    "VIEW_REPORTS": (NONE, NONE, ALL),
}
ROLES = ("student", "instructor", "admin")
CELLS = [
    (action, role, MATRIX[action][i]) for action in MATRIX for i, role in enumerate(ROLES)
]

ACTOR_ID = 10
OTHER_ID = 99


def permissions():
    return importlib.import_module("lineup.permissions")


def models():
    return importlib.import_module("lineup.models")


def actor(role, member_id=ACTOR_ID):
    m = models()
    return m.Actor(
        id=member_id, email=f"m{member_id}@novasbe.pt", full_name="Test Member",
        role=m.Role(role), level=m.Level.BEGINNER,
    )


def assert_forbidden(result):
    m = models()
    assert result is not None
    assert result.ok is False
    assert result.code is m.Code.FORBIDDEN
    assert result.message == m.MESSAGES[m.Code.FORBIDDEN]


def test_section3_action_enum_covers_the_whole_matrix():
    assert {a.name for a in permissions().Action} == set(MATRIX)


@pytest.mark.parametrize("action, role, rule", CELLS, ids=[f"{a}-{r}" for a, r, _ in CELLS])
def test_section3_permission_matrix_cell(action, role, rule):
    p = permissions()
    who = actor(role)
    # "own" cells are checked with the actor's own record; others with a stranger's.
    owner_id = ACTOR_ID if rule == OWN else OTHER_ID
    result = p.require(who, p.Action[action], owner_id)
    if rule == NONE:
        assert_forbidden(result)
    else:
        assert result is None


@pytest.mark.parametrize(
    "action, role",
    [(a, r) for a, r, rule in CELLS if rule == OWN],
)
def test_section3_own_only_cell_refuses_another_members_record(action, role):
    p = permissions()
    assert_forbidden(p.require(actor(role), p.Action[action], OTHER_ID))


def test_r5_1_student_cancelling_another_students_booking_is_forbidden():
    p = permissions()
    assert_forbidden(p.require(actor("student"), p.Action.CANCEL_BOOKING, OTHER_ID))


def test_r5_1_student_cancelling_own_booking_is_allowed():
    p = permissions()
    assert p.require(actor("student"), p.Action.CANCEL_BOOKING, ACTOR_ID) is None


def test_r8_1_instructor_calling_off_another_instructors_session_is_forbidden():
    p = permissions()
    assert_forbidden(p.require(actor("instructor"), p.Action.CALL_OFF, OTHER_ID))


def test_r8_1_instructor_calling_off_own_session_is_allowed():
    p = permissions()
    assert p.require(actor("instructor"), p.Action.CALL_OFF, ACTOR_ID) is None


def test_section3_instructor_editing_another_instructors_session_is_forbidden():
    p = permissions()
    assert_forbidden(p.require(actor("instructor"), p.Action.MANAGE_OWN_SESSIONS, OTHER_ID))


def test_section3_admin_acts_on_any_session():
    p = permissions()
    assert p.require(actor("admin"), p.Action.CALL_OFF, OTHER_ID) is None


def test_section3_own_cell_without_owner_id_is_forbidden_for_a_student():
    p = permissions()
    assert_forbidden(p.require(actor("student"), p.Action.BOOK))


def test_section3_own_cell_without_owner_id_is_forbidden_for_an_instructor():
    p = permissions()
    assert_forbidden(p.require(actor("instructor"), p.Action.MANAGE_OWN_SESSIONS))


def test_section3_all_cell_needs_no_owner_id():
    p = permissions()
    assert p.require(actor("student"), p.Action.VIEW_SESSIONS) is None


@pytest.mark.parametrize("action", list(MATRIX))
def test_section3_no_actor_is_forbidden(action):
    p = permissions()
    assert_forbidden(p.require(None, p.Action[action], ACTOR_ID))
