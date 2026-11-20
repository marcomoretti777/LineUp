"""Tests for the pure credit request rules and money formatting (R10.2-R10.6)."""

import pytest

from lineup.logic.credits import (
    check_can_decide,
    check_can_request,
    check_can_withdraw,
    fmt_eur,
    price_per_credit_cents,
    validate_note,
    validate_payment_ref,
)
from lineup.models import Code, RequestStatus, Role


# ---------- R10.3 payment reference ----------

def test_r10_3_payment_ref_accepts_plain():
    clean, err = validate_payment_ref("MBWAY 912")
    assert err is None
    assert clean == "MBWAY 912"


def test_r10_3_payment_ref_trims_and_accepts_symbols():
    clean, err = validate_payment_ref(" MB-WAY #12/3 ")
    assert err is None
    assert clean == "MB-WAY #12/3"


def test_r10_3_payment_ref_rejects_too_short():
    _, err = validate_payment_ref("ab")
    assert err is not None and not err.ok
    assert err.code == Code.INVALID


def test_r10_3_payment_ref_accepts_40_characters():
    clean, err = validate_payment_ref("a" * 40)
    assert err is None
    assert clean == "a" * 40


def test_r10_3_payment_ref_rejects_41_characters():
    _, err = validate_payment_ref("a" * 41)
    assert err is not None and not err.ok
    assert err.code == Code.INVALID


def test_r10_3_payment_ref_rejects_html():
    _, err = validate_payment_ref("<b>x</b>")
    assert err is not None and not err.ok
    assert err.code == Code.INVALID


def test_r10_3_payment_ref_rejects_semicolon():
    _, err = validate_payment_ref("a;b")
    assert err is not None and not err.ok
    assert err.code == Code.INVALID


# ---------- R10.5 note ----------

def test_r10_5_note_rejects_too_short():
    err = validate_note("ab")
    assert err is not None and not err.ok
    assert err.code == Code.INVALID


@pytest.mark.parametrize("length", [3, 200])
def test_r10_5_note_accepts_3_to_200_characters(length):
    assert validate_note("n" * length) is None


def test_r10_5_note_rejects_201_characters():
    err = validate_note("n" * 201)
    assert err is not None and not err.ok
    assert err.code == Code.INVALID


# ---------- R10.2 can request ----------

def test_r10_2_request_rejects_duplicate_pending():
    err = check_can_request(role=Role.STUDENT, has_pending=True, pack_active=True)
    assert err is not None and not err.ok
    assert err.code == Code.DUPLICATE


def test_r10_2_request_rejects_inactive_or_unknown_pack():
    err = check_can_request(role=Role.STUDENT, has_pending=False, pack_active=False)
    assert err is not None and not err.ok
    assert err.code == Code.INVALID


@pytest.mark.parametrize("role", [Role.INSTRUCTOR, Role.ADMIN])
def test_r10_2_request_rejects_non_student(role):
    err = check_can_request(role=role, has_pending=False, pack_active=True)
    assert err is not None and not err.ok
    assert err.code == Code.FORBIDDEN


def test_r10_2_request_allows_student_with_active_pack():
    assert check_can_request(role=Role.STUDENT, has_pending=False, pack_active=True) is None


# ---------- R10.4 can withdraw ----------

def test_r10_4_withdraw_rejects_non_owner():
    err = check_can_withdraw(is_owner=False, status=RequestStatus.PENDING)
    assert err is not None and not err.ok
    assert err.code == Code.FORBIDDEN


@pytest.mark.parametrize(
    "status", [RequestStatus.APPROVED, RequestStatus.REJECTED, RequestStatus.WITHDRAWN]
)
def test_r10_4_withdraw_rejects_not_pending(status):
    err = check_can_withdraw(is_owner=True, status=status)
    assert err is not None and not err.ok
    assert err.code == Code.ALREADY_DONE


def test_r10_4_withdraw_allows_own_pending():
    assert check_can_withdraw(is_owner=True, status=RequestStatus.PENDING) is None


# ---------- R10.6 can decide ----------

def test_r10_6_decide_allows_pending():
    assert check_can_decide(status=RequestStatus.PENDING) is None


@pytest.mark.parametrize(
    "status", [RequestStatus.APPROVED, RequestStatus.REJECTED, RequestStatus.WITHDRAWN]
)
def test_r10_6_decide_rejects_already_decided(status):
    err = check_can_decide(status=status)
    assert err is not None and not err.ok
    assert err.code == Code.ALREADY_DONE


# ---------- money ----------

@pytest.mark.parametrize("cents, expected", [(1500, "€15.00"), (6500, "€65.00")])
def test_money_fmt_eur(cents, expected):
    assert fmt_eur(cents) == expected


def test_money_price_per_credit_cents():
    assert price_per_credit_cents(6500, 5) == 1300
