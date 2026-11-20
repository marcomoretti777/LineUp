"""Pure sign-up rules: what an address, a name and a password must look like.

No database, network or clock here (AGENTS.md). Each validate_* returns None
when the value is fine, so a caller reads `if refusal: return refusal`.
Normalising is separate, because a validator returning None has nowhere to
hand a cleaned value back.
"""

from __future__ import annotations

from lineup.config import ALLOWED_EMAIL_DOMAIN
from lineup.models import Code, Result, fill

NAME_MIN = 2
NAME_MAX = 60
PASSWORD_MIN = 8

# Letters already cover accents through str.isalpha; these are the marks a
# name may also carry, as in "Joao D'Avila" or "Ana-Maria St.".
_NAME_MARKS = frozenset(" -'.")


def _invalid(field: str, problem: str, allowed: str) -> Result:
    """Build the catalogue INVALID message for one field.

    Rules: section 11 (message catalogue).
    """
    return Result.fail(
        Code.INVALID, fill(Code.INVALID, field=field, problem=problem, allowed=allowed)
    )


def normalise_email(raw: str | None) -> str:
    """Return an address trimmed and lower-cased, the form stored and compared.

    Rules: R1.1.
    """
    return (raw or "").strip().lower()


def normalise_name(raw: str | None) -> str:
    """Return a name trimmed, with runs of whitespace collapsed to one space.

    Rules: R1.2.
    """
    return " ".join((raw or "").split())


def validate_email(raw: str | None) -> Result | None:
    """Refuse any address that is not a single club address, else None.

    The domain is compared for equality, which rejects another domain, a
    subdomain and a second @ in one test.

    Rules: R1.1.
    """
    email = normalise_email(raw)
    local, separator, domain = email.partition("@")
    if not separator or not local or domain != ALLOWED_EMAIL_DOMAIN:
        return _invalid(
            "Email", "that is not a club address", f"name@{ALLOWED_EMAIL_DOMAIN}"
        )
    return None


def validate_name(raw: str | None) -> Result | None:
    """Refuse a name outside 2-60 characters or holding anything but letters.

    Rules: R1.2.
    """
    name = normalise_name(raw)
    allowed = (
        f"{NAME_MIN}-{NAME_MAX} characters: letters, spaces, hyphens, "
        "apostrophes and full stops"
    )
    if not NAME_MIN <= len(name) <= NAME_MAX:
        return _invalid("Full name", f"it is {len(name)} characters", allowed)
    if not all(character.isalpha() or character in _NAME_MARKS for character in name):
        return _invalid("Full name", "it has characters a name cannot hold", allowed)
    return None


def validate_password(password: str | None, confirmation: str | None = None) -> Result | None:
    """Refuse a password under 8 characters, or one its confirmation misses.

    The refusal never repeats the password or its length, because the message
    is shown on screen and may be logged.

    Rules: R1.3, section 12 (secrets).
    """
    allowed = f"at least {PASSWORD_MIN} characters"
    if len(password or "") < PASSWORD_MIN:
        return _invalid("Password", "it is too short", allowed)
    if confirmation is not None and confirmation != password:
        return _invalid("Password", "the confirmation does not match it", allowed)
    return None
