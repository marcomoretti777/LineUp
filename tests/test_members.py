"""First-login profiles and admin role and level changes (R1.4-R1.6)."""

import pytest
from sqlalchemy import select

from lineup import db, schema
from lineup.models import Code, Level, Role
from lineup.permissions import Action, require
from lineup.services import members
from tests.conftest import make_member


def role_of(engine, member_id):
    """Read a member's role straight from storage, bypassing any cache."""
    with engine.begin() as conn:
        return conn.execute(
            select(schema.members.c.role).where(schema.members.c.id == member_id)
        ).scalar_one()


def level_of(engine, member_id):
    """Read a member's level straight from storage."""
    with engine.begin() as conn:
        return conn.execute(
            select(schema.members.c.level).where(schema.members.c.id == member_id)
        ).scalar_one()


# --- R1.4 first login ------------------------------------------------------

def test_r1_4_unknown_account_becomes_a_student_at_beginner(engine):
    result = members.login_member(engine, "auth-new", "new@novasbe.pt", "New Member")
    assert result.ok is True
    member_id = result.data
    with engine.begin() as conn:
        actor = db.get_actor(conn, member_id)
    assert actor.role == Role.STUDENT
    assert actor.level == Level.BEGINNER
    assert actor.email == "new@novasbe.pt"


def test_r1_4_new_profile_is_created_once_not_on_every_login(engine):
    first = members.login_member(engine, "auth-new", "new@novasbe.pt", "New Member")
    second = members.login_member(engine, "auth-new", "new@novasbe.pt", "New Member")
    assert first.data == second.data
    with engine.begin() as conn:
        count = conn.execute(select(schema.members.c.id)).all()
    assert len(count) == 1


def test_seeded_email_is_linked_to_the_auth_account_keeping_its_role(engine):
    seeded = make_member(engine, role="admin", level="intermediate", email="rita@novasbe.pt")
    result = members.login_member(engine, "auth-rita", "rita@novasbe.pt", "Rita Admin")
    assert result.data == seeded
    with engine.begin() as conn:
        row = conn.execute(
            select(schema.members.c.auth_user_id, schema.members.c.role, schema.members.c.level)
            .where(schema.members.c.id == seeded)
        ).one()
    assert row.auth_user_id == "auth-rita"
    assert row.role == Role.ADMIN
    assert row.level == Level.INTERMEDIATE


def test_login_matches_a_seeded_email_regardless_of_case_and_spacing(engine):
    seeded = make_member(engine, email="ana@novasbe.pt")
    result = members.login_member(engine, "auth-ana", "  Ana@NovaSBE.pt  ", "Ana Silva")
    assert result.data == seeded


# --- R1.5 only admins change roles and levels ------------------------------

def test_r1_5_admin_changes_a_role(engine):
    admin = make_member(engine, role="admin")
    student = make_member(engine, role="student")
    result = members.change_role(engine, admin, student, Role.INSTRUCTOR)
    assert result.ok is True
    assert role_of(engine, student) == Role.INSTRUCTOR


def test_r1_5_instructor_cannot_change_a_role(engine):
    instructor = make_member(engine, role="instructor")
    student = make_member(engine, role="student")
    result = members.change_role(engine, instructor, student, Role.ADMIN)
    assert result.ok is False
    assert result.code is Code.FORBIDDEN
    assert role_of(engine, student) == Role.STUDENT


def test_r1_5_admin_changes_a_level(engine):
    admin = make_member(engine, role="admin")
    student = make_member(engine, role="student")
    result = members.change_level(engine, admin, student, Level.INTERMEDIATE)
    assert result.ok is True
    assert level_of(engine, student) == Level.INTERMEDIATE


def test_r1_5_student_cannot_change_a_level(engine):
    student = make_member(engine, role="student")
    other = make_member(engine, role="student")
    result = members.change_level(engine, student, other, Level.INTERMEDIATE)
    assert result.ok is False
    assert result.code is Code.FORBIDDEN
    assert level_of(engine, other) == Level.BEGINNER


# --- R1.6 there is always at least one admin -------------------------------

def test_r1_6_demoting_the_only_admin_is_refused_and_changes_nothing(engine):
    admin = make_member(engine, role="admin")
    result = members.change_role(engine, admin, admin, Role.STUDENT)
    assert result.ok is False
    assert result.code is Code.INVALID
    assert role_of(engine, admin) == Role.ADMIN


def test_r1_6_demoting_an_admin_is_allowed_while_another_admin_remains(engine):
    first = make_member(engine, role="admin")
    second = make_member(engine, role="admin")
    result = members.change_role(engine, first, second, Role.STUDENT)
    assert result.ok is True
    assert role_of(engine, second) == Role.STUDENT
    assert role_of(engine, first) == Role.ADMIN


def test_r1_6_the_last_admin_may_still_be_given_another_level(engine):
    admin = make_member(engine, role="admin")
    result = members.change_level(engine, admin, admin, Level.INTERMEDIATE)
    assert result.ok is True
    assert role_of(engine, admin) == Role.ADMIN


# --- the role is read fresh on every action --------------------------------

def test_a_demoted_instructor_loses_rights_on_the_very_next_call(engine):
    admin = make_member(engine, role="admin")
    instructor = make_member(engine, role="instructor")

    with engine.begin() as conn:
        before = db.get_actor(conn, instructor)
    assert require(before, Action.MANAGE_OWN_SESSIONS, owner_id=instructor) is None

    assert members.change_role(engine, admin, instructor, Role.STUDENT).ok is True

    with engine.begin() as conn:
        after = db.get_actor(conn, instructor)
    denied = require(after, Action.MANAGE_OWN_SESSIONS, owner_id=instructor)
    assert denied is not None
    assert denied.code is Code.FORBIDDEN


# --- the member is told what an admin changed ------------------------------

def test_a_role_change_notifies_the_member_in_the_same_transaction(engine):
    admin = make_member(engine, role="admin")
    student = make_member(engine, role="student")
    members.change_role(engine, admin, student, Role.INSTRUCTOR)
    with engine.begin() as conn:
        assert db.unread_count(conn, student) == 1


# --- listing ---------------------------------------------------------------

def test_list_members_is_refused_to_a_student(engine):
    student = make_member(engine, role="student")
    result = members.list_members(engine, student)
    assert result.ok is False
    assert result.code is Code.FORBIDDEN


def test_list_members_returns_every_member_to_an_admin(engine):
    admin = make_member(engine, role="admin")
    make_member(engine, role="student")
    result = members.list_members(engine, admin)
    assert result.ok is True
    assert len(result.data) == 2


def test_demo_picker_lists_members_without_an_actor(engine):
    make_member(engine, role="admin", name="Rita Admin")
    make_member(engine, role="student", name="Ana Silva")
    listed = members.list_demo_members(engine)
    assert [name for _, name, _ in listed] == ["Ana Silva", "Rita Admin"]
    assert [role for _, _, role in listed] == ["student", "admin"]


def test_list_members_can_be_searched_by_name_or_email(engine):
    admin = make_member(engine, role="admin", name="Marta Silva",
                        email="lineup.admin@novasbe.pt")
    make_member(engine, role="student", name="Ana Martins",
                email="lineup.ana@novasbe.pt")
    make_member(engine, role="student", name="Bruno Lopes",
                email="lineup.bruno@novasbe.pt")

    by_name = members.list_members(engine, admin, search="ana")
    assert [m["full_name"] for m in by_name.data] == ["Ana Martins"]

    by_email = members.list_members(engine, admin, search="BRUNO@")
    assert [m["full_name"] for m in by_email.data] == ["Bruno Lopes"]

    assert len(members.list_members(engine, admin, search="   ").data) == 3


# --- R1.4 re-created Supabase accounts --------------------------------------
# Deleting a user in the Supabase dashboard leaves the LineUp profile behind,
# still pointing at the old auth id. When the person signs up again, Supabase
# gives the same address a new auth id; the profile must follow it instead
# of a second profile being inserted for the same address.


def set_auth_id(engine, member_id, auth_user_id):
    with engine.begin() as conn:
        conn.execute(
            schema.members.update()
            .where(schema.members.c.id == member_id)
            .values(auth_user_id=auth_user_id)
        )


def auth_id_of(engine, member_id):
    with engine.begin() as conn:
        return conn.execute(
            select(schema.members.c.auth_user_id).where(schema.members.c.id == member_id)
        ).scalar_one()


def test_r1_4_recreated_supabase_account_takes_over_its_old_profile(engine):
    diogo = make_member(engine, name="Diogo Alves", email="75080@novasbe.pt")
    set_auth_id(engine, diogo, "auth-deleted")

    result = members.login_member(engine, "auth-recreated", "75080@novasbe.pt", "Diogo Alves")

    assert result.ok is True
    assert result.data == diogo
    assert auth_id_of(engine, diogo) == "auth-recreated"
    with engine.begin() as conn:
        rows = conn.execute(
            select(schema.members.c.id).where(schema.members.c.email == "75080@novasbe.pt")
        ).all()
    assert len(rows) == 1


def test_r1_4_recreated_account_keeps_its_role_and_level(engine):
    marta = make_member(engine, role="admin", level="intermediate", email="marta@novasbe.pt")
    set_auth_id(engine, marta, "auth-deleted")

    members.login_member(engine, "auth-recreated", "Marta@NovaSBE.pt", "Marta Silva")

    assert role_of(engine, marta) == Role.ADMIN.value
    assert level_of(engine, marta) == Level.INTERMEDIATE.value


def test_r1_4_recreated_account_logs_in_normally_afterwards(engine):
    diogo = make_member(engine, email="75080@novasbe.pt")
    set_auth_id(engine, diogo, "auth-deleted")
    members.login_member(engine, "auth-recreated", "75080@novasbe.pt")

    again = members.login_member(engine, "auth-recreated", "75080@novasbe.pt")

    assert again.ok is True
    assert again.data == diogo
