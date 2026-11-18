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


def validate_payment_ref(text: str) -> tuple[str, Result | None]:
    """Trim a payment reference and check its length and characters.

    Rules: R10.3 - after trimming, 3 to 40 characters made only of letters,
    digits, spaces and the symbols - / #; anything else is INVALID.
    """
    clean = (text or "").strip()
    if not PAYMENT_REF_MIN <= len(clean) <= PAYMENT_REF_MAX:
        return clean, Result.fail(Code.INVALID, fill(Code.INVALID))
    if not _PAYMENT_REF_PATTERN.fullmatch(clean):
        return clean, Result.fail(Code.INVALID, fill(Code.INVALID))
    return clean, None


def validate_note(text: str) -> Result | None:
    """Check that a request note has an acceptable length.

    Rules: R10.5 - after trimming, 3 to 200 characters; otherwise INVALID.
    """
    clean = (text or "").strip()
    if not NOTE_MIN <= len(clean) <= NOTE_MAX:
        return Result.fail(Code.INVALID, fill(Code.INVALID))
    return None


def check_can_request(*, role: Role, has_pending: bool, pack_active: bool) -> Result | None:
    """Decide whether a user may submit a new credit request.

    Rules: R10.2 - only students may request (else FORBIDDEN); the pack must
    exist and be active (else INVALID); a student with a pending request may
    not open another (else DUPLICATE). Checked in that order.
    """
    if role != Role.STUDENT:
        return Result.fail(Code.FORBIDDEN, fill(Code.FORBIDDEN))
    if not pack_active:
        return Result.fail(Code.INVALID, fill(Code.INVALID))
    if has_pending:
        return Result.fail(Code.DUPLICATE, fill(Code.DUPLICATE))
    return None


def check_can_withdraw(*, is_owner: bool, status: RequestStatus) -> Result | None:
    """Decide whether a user may withdraw a credit request.

    Rules: R10.4 - only the request's owner may withdraw it (else FORBIDDEN),
    and only while it is pending (else ALREADY_DONE).
    """
    if not is_owner:
        return Result.fail(Code.FORBIDDEN, fill(Code.FORBIDDEN))
    if status != RequestStatus.PENDING:
        return Result.fail(Code.ALREADY_DONE, fill(Code.ALREADY_DONE))
    return None


def check_can_decide(*, status: RequestStatus) -> Result | None:
    """Decide whether a credit request can still be approved or rejected.

    Rules: R10.6 - only pending requests can be decided; approved, rejected
    or withdrawn requests are ALREADY_DONE.
    """
    if status != RequestStatus.PENDING:
        return Result.fail(Code.ALREADY_DONE, fill(Code.ALREADY_DONE))
    return None


def fmt_eur(cents: int) -> str:
    """Format an integer amount of cents as a euro string like "€15.00".

    Rules: money stays integer cents until display; no float arithmetic.
    """
    sign = "-" if cents < 0 else ""
    whole, rest = divmod(abs(cents), 100)
    return f"{sign}€{whole}.{rest:02d}"


def price_per_credit_cents(price_cents: int, credits: int) -> int:
    """Return the price of one credit in a pack, in integer cents.

    Rules: integer cents only, rounded down; credits must be positive
    (raises ValueError otherwise).
    """
    if credits <= 0:
        raise ValueError("credits must be positive")
    return price_cents // credits
