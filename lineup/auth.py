"""The only module that talks to Supabase Auth.

Supabase checks passwords; LineUp never sees or stores one. A client is
built for each attempt and never cached, because it holds one user's
session (spec section 12, Login). Callers may inject a client factory, so
tests never reach the network.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from lineup import config
from lineup.logic.accounts import (
    normalise_email,
    normalise_name,
    validate_email,
    validate_name,
    validate_password,
)
from lineup.models import Code, Result, fill

_LOG = logging.getLogger(__name__)

# One wording for a wrong address and a wrong password alike, so the reply
# cannot be used to learn which addresses have accounts.
WRONG_CREDENTIALS = "Email or password is wrong."

SIGN_UP_FAILED = "Could not create the account. Please try again."

# Supabase Auth error codes a sign-up can hit, and what the member should
# read instead of one catch-all sentence. Several depend on project
# settings only an admin can change, so those say who to ask.
_SIGN_UP_REFUSALS = {
    "user_already_exists": "An account with this address already exists. Log in instead.",
    "email_exists": "An account with this address already exists. Log in instead.",
    "email_address_invalid": (
        "The sign-up service refused this address. Please tell a club admin."
    ),
    "email_address_not_authorized": (
        "The sign-up service refused this address. Please tell a club admin."
    ),
    "over_email_send_rate_limit": (
        "Too many sign-ups in a short time. Please wait a few minutes and try again."
    ),
    "over_request_rate_limit": (
        "Too many sign-ups in a short time. Please wait a few minutes and try again."
    ),
    "signup_disabled": "Sign-up is closed at the moment. Please tell a club admin.",
    "email_provider_disabled": "Sign-up is closed at the moment. Please tell a club admin.",
}

# Reasons Supabase gives with a weak_password refusal.
_WEAK_PASSWORD_REASONS = {
    "length": "it is too short for the sign-up service",
    "characters": "it needs lower case, upper case, digits and symbols",
    "pwned": "it appears in a known data leak",
}

ClientFactory = Callable[[], Any]


def _default_client_factory() -> Any:
    """Build a fresh Supabase client from the configured settings.

    supabase is imported here, not at module level, so logic and tests can
    import this module without the package or any secrets.

    Rules: section 12 (secrets, login).
    """
    url = config.get_secret("SUPABASE_URL")
    key = config.get_secret("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Supabase is not configured")

    from supabase import create_client

    return create_client(url, key)


def _user_data(response: Any, email: str) -> dict | None:
    """Pull the auth id and confirmation state out of a Supabase response.

    Rules: R1.4.
    """
    user = getattr(response, "user", None)
    if user is None or not getattr(user, "id", None):
        return None
    return {
        "auth_user_id": user.id,
        "email": getattr(user, "email", None) or email,
        "needs_confirmation": getattr(user, "email_confirmed_at", None) is None,
    }


def _sign_up_refusal(error: Exception) -> Result:
    """Turn a Supabase sign-up error into the reason the member should read.

    Reads the error's `code` attribute instead of importing Supabase's
    classes, so this module still imports without the package.

    Rules: R1.1, R1.3, R1.4, section 11 (errors name the reason).
    """
    code = getattr(error, "code", None)
    if code == "weak_password":
        reasons = [
            _WEAK_PASSWORD_REASONS[reason]
            for reason in getattr(error, "reasons", None) or []
            if reason in _WEAK_PASSWORD_REASONS
        ]
        problem = " and ".join(reasons) or "the sign-up service finds it too weak"
        return Result.fail(
            Code.INVALID,
            fill(Code.INVALID, field="Password", problem=problem,
                 allowed="a longer password that is not used elsewhere"),
            data={"field": "password"},
        )
    return Result.fail(Code.INVALID, _SIGN_UP_REFUSALS.get(code, SIGN_UP_FAILED))


def sign_up(email: str, password: str, full_name: str,
            client_factory: ClientFactory | None = None) -> Result:
    """Create a Supabase account for a club address, after checking the fields.

    Validation runs before any client is built, so a refused address costs
    no network call. The password is never logged.

    Rules: R1.1, R1.2, R1.3, section 12 (login).
    """
    for refusal in (validate_email(email), validate_name(full_name),
                    validate_password(password)):
        if refusal:
            return refusal

    address = normalise_email(email)
    name = normalise_name(full_name)
    factory = client_factory or _default_client_factory
    try:
        client = factory()
        response = client.auth.sign_up({
            "email": address,
            "password": password,
            "options": {"data": {"full_name": name}},
        })
    except Exception as error:
        # The code and status say why Supabase refused; the credentials and
        # Supabase's own text (which can repeat the address) stay out.
        code = getattr(error, "code", None)
        if code:
            _LOG.warning("Supabase refused a sign-up: code=%s status=%s",
                         code, getattr(error, "status", None))
        else:
            _LOG.exception("Supabase sign-up failed for a club address")
        return _sign_up_refusal(error)

    data = _user_data(response, address)
    if data is None:
        _LOG.warning("Supabase sign-up returned no user")
        return Result.fail(Code.INVALID, SIGN_UP_FAILED)
    data["full_name"] = name
    return Result.success("Account created.", data)


def sign_in(email: str, password: str,
            client_factory: ClientFactory | None = None) -> Result:
    """Check an address and password with Supabase and return the auth id.

    Every refusal is worded the same, so the reply never reveals whether an
    address exists. The password is never logged.

    Rules: R1.1, section 12 (login).
    """
    if validate_email(email):
        return Result.fail(Code.INVALID, WRONG_CREDENTIALS)

    address = normalise_email(email)
    factory = client_factory or _default_client_factory
    try:
        client = factory()
        response = client.auth.sign_in_with_password({
            "email": address,
            "password": password,
        })
    except Exception:
        _LOG.exception("Supabase sign-in failed for %s", address)
        return Result.fail(Code.INVALID, WRONG_CREDENTIALS)

    data = _user_data(response, address)
    if data is None:
        return Result.fail(Code.INVALID, WRONG_CREDENTIALS)
    return Result.success("Signed in.", data)
