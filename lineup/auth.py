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
from lineup.models import Code, Result

_LOG = logging.getLogger(__name__)

# One wording for a wrong address and a wrong password alike, so the reply
# cannot be used to learn which addresses have accounts.
WRONG_CREDENTIALS = "Email or password is wrong."

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
    except Exception:
        # Logged without the credentials; the member sees a plain sentence.
        _LOG.exception("Supabase sign-up failed for a club address")
        return Result.fail(Code.INVALID, "Could not create the account. Please try again.")

    data = _user_data(response, address)
    if data is None:
        return Result.fail(Code.INVALID, "Could not create the account. Please try again.")
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
