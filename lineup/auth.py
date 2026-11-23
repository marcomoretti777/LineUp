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

# Supabase Auth error codes a sign-up can hit, each rewritten as the reason
# in plain words plus what to do next. The codes themselves mean nothing to
# a member, so they only go to the log. Codes that depend on project
# settings say that a club admin has to change them.
_SIGN_UP_REFUSALS = {
    "user_already_exists": (
        "An account with this address already exists, probably from an earlier "
        "sign-up. Log in instead, with the password you chose then."
    ),
    "email_exists": (
        "An account with this address already exists, probably from an earlier "
        "sign-up. Log in instead, with the password you chose then."
    ),
    "email_address_invalid": (
        "The sign-up service does not accept this address as a real mailbox. "
        "Check it for typos; if it is right, please tell a club admin."
    ),
    "email_address_not_authorized": (
        "The sign-up service can only send confirmation emails to the club's own "
        "team, so it cannot email this address. A club admin needs to turn off "
        "email confirmation or connect an email provider."
    ),
    "over_email_send_rate_limit": (
        "The sign-up service has sent as many confirmation emails as it is allowed "
        "this hour, so it is pausing new accounts. Please try again in an hour."
    ),
    "over_request_rate_limit": (
        "Too many sign-up attempts came from this network in a short time, so the "
        "sign-up service is pausing them. Please wait a few minutes and try again."
    ),
    "signup_disabled": (
        "Creating new accounts is switched off in the sign-up service right now. "
        "Please tell a club admin."
    ),
    "email_provider_disabled": (
        "Signing up with an email address is switched off in the sign-up service. "
        "Please tell a club admin."
    ),
    "validation_failed": (
        "The sign-up service could not read the details as sent. Check the email "
        "address and password, then try again."
    ),
    "captcha_failed": (
        "The sign-up service asked for a robot check that this page cannot show. "
        "Please tell a club admin."
    ),
    "unexpected_failure": (
        "The sign-up service had a problem on its side. Please try again in a few minutes."
    ),
    "request_timeout": (
        "The sign-up service took too long to answer. Please try again in a few minutes."
    ),
}

# Reasons Supabase gives with a weak_password refusal, in plain words.
_WEAK_PASSWORD_REASONS = {
    "length": "it is shorter than the sign-up service requires",
    "characters": "it needs a mix of lower case, upper case, digits and symbols",
    "pwned": "it appears in a known data leak, so attackers may already try it",
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
        # Semicolons, because a reason can itself contain commas.
        if len(reasons) == 2:
            problem = " and ".join(reasons)
        elif len(reasons) > 2:
            problem = "; ".join(reasons[:-1]) + "; and " + reasons[-1]
        else:
            problem = reasons[0] if reasons else "the sign-up service finds it too weak"
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
