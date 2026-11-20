"""Pure rules for credit requests and money formatting (R10.2-R10.6).

No database, UI, network or clock access: callers pass in plain facts and
get back ``None`` (allowed) or a failed ``Result`` explaining why not.
Money is always integer cents until it is formatted for display.
"""

import re

from lineup.models import Code, RequestStatus, Result, Role, fill

PAYMENT_REF_MIN = 3
PAYMENT_REF_MAX = 40
NOTE_MIN = 3
NOTE_MAX = 200

_PAYMENT_REF_PATTERN = re.compile(r"[A-Za-z0-9 \-/#]+")


def _invalid(field: str, problem: str, allowed: str) -> Result:
    """Build an INVALID result with the catalogue message filled in.

    Rules: section 11 (INVALID needs field, problem and allowed).
    """
    message = fill(Code.INVALID, field=field, problem=problem, allowed=allowed)
    return Result.fail(Code.INVALID, message)


def validate_payment_ref(text: str) -> tuple[str, Result | None]:
    """Trim a payment reference and check its length and characters.

    After trimming it must be 3 to 40 characters made only of letters,
    digits, spaces and the symbols - / #; anything else is INVALID.

    Rules: R10.3.
    """
    clean = (text or "").strip()
    if not PAYMENT_REF_MIN <= len(clean) <= PAYMENT_REF_MAX:
        return clean, _invalid(
            "Payment reference",
            f"it has {len(clean)} characters",
            f"{PAYMENT_REF_MIN} to {PAYMENT_REF_MAX} characters",
        )
    if not _PAYMENT_REF_PATTERN.fullmatch(clean):
        return clean, _invalid(
            "Payment reference",
            "it contains a character that is not allowed",
            "letters, digits, spaces and - / #",
        )
    return clean, None


def validate_note(text: str) -> Result | None:
    """Check that a request note has an acceptable length.

    After trimming it must be 3 to 200 characters; otherwise INVALID.

    Rules: R10.5.
    """
    clean = (text or "").strip()
    if not NOTE_MIN <= len(clean) <= NOTE_MAX:
        return _invalid(
            "Note",
            f"it has {len(clean)} characters",
            f"{NOTE_MIN} to {NOTE_MAX} characters",
        )
    return None


def check_can_request(*, role: Role, has_pending: bool, pack_active: bool) -> Result | None:
    """Decide whether a user may submit a new credit request.

    Only students may request (else FORBIDDEN); the pack must exist and be
    active (else INVALID); a student with a pending request may not open
    another (else DUPLICATE). Checked in that order.

    Rules: R10.2.
    """
    if role != Role.STUDENT:
        return Result.fail(Code.FORBIDDEN, fill(Code.FORBIDDEN))
    if not pack_active:
        return _invalid("Pack", "it is not available", "an active credit pack")
    if has_pending:
        return Result.fail(Code.DUPLICATE, fill(Code.DUPLICATE))
    return None


def check_can_withdraw(*, is_owner: bool, status: RequestStatus) -> Result | None:
    """Decide whether a user may withdraw a credit request.

    Only the request's owner may withdraw it (else FORBIDDEN), and only while
    it is pending (else ALREADY_DONE).

    Rules: R10.4.
    """
    if not is_owner:
        return Result.fail(Code.FORBIDDEN, fill(Code.FORBIDDEN))
    if status != RequestStatus.PENDING:
        return Result.fail(Code.ALREADY_DONE, fill(Code.ALREADY_DONE))
    return None


def check_can_decide(*, status: RequestStatus) -> Result | None:
    """Decide whether a credit request can still be approved or rejected.

    Only pending requests can be decided; approved, rejected or withdrawn
    requests are ALREADY_DONE.

    Rules: R10.6.
    """
    if status != RequestStatus.PENDING:
        return Result.fail(Code.ALREADY_DONE, fill(Code.ALREADY_DONE))
    return None


def fmt_eur(cents: int) -> str:
    """Format an integer amount of cents as a euro string like "€15.00".

    Money stays integer cents until display; no float arithmetic.

    Rules: R10.1, section 9 (money in cents).
    """
    sign = "-" if cents < 0 else ""
    whole, rest = divmod(abs(cents), 100)
    return f"{sign}€{whole}.{rest:02d}"


def price_per_credit_cents(price_cents: int, credits: int) -> int:
    """Return the price of one credit in a pack, in integer cents.

    Integer cents only, rounded down; credits must be positive (raises
    ValueError otherwise).

    Rules: R10.1.
    """
    if credits <= 0:
        raise ValueError("credits must be positive")
    return price_cents // credits
