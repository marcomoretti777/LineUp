"""Sign-up validation rules and the Supabase Auth wrapper (R1.1-R1.3).

No test here touches the network: the auth wrapper takes a client factory,
and these tests inject a fake one. No test prints or asserts on a password.
"""

import pytest

from lineup import auth
from lineup.logic import accounts
from lineup.models import Code

# Long enough to pass R1.3, so a test never fails for the wrong reason.
GOOD_PASSWORD = "surfs-up-2026"


class FakeAuth:
    """The .auth attribute of a fake Supabase client."""

    def __init__(self, client, raises=False, confirmed=True):
        self._client = client
        self._raises = raises
        self._confirmed = confirmed

    def _answer(self, credentials):
        self._client.seen_emails.append(credentials["email"])
        if self._raises:
            raise RuntimeError("supabase said no")

        class User:
            id = "auth-uid-1"
            email = credentials["email"]
            email_confirmed_at = "2026-11-20T09:00:00Z" if self._confirmed else None

        class Response:
            user = User()

        return Response()

    def sign_in_with_password(self, credentials):
        return self._answer(credentials)

    def sign_up(self, credentials):
        return self._answer(credentials)


class FakeClient:
    """Stands in for a Supabase client; records the addresses it was given."""

    def __init__(self, raises=False, confirmed=True):
        self.seen_emails = []
        self.auth = FakeAuth(self, raises=raises, confirmed=confirmed)


class CountingFactory:
    """A client factory that counts how often it was asked for a client."""

    def __init__(self, raises=False, confirmed=True):
        self.calls = 0
        self.clients = []
        self._raises = raises
        self._confirmed = confirmed

    def __call__(self):
        self.calls += 1
        client = FakeClient(raises=self._raises, confirmed=self._confirmed)
        self.clients.append(client)
        return client


# --- R1.1 email ------------------------------------------------------------

def test_r1_1_email_is_trimmed_and_lower_cased():
    assert accounts.normalise_email("  Ana@NovaSBE.pt  ") == "ana@novasbe.pt"


def test_r1_1_padded_mixed_case_novasbe_email_is_accepted():
    assert accounts.validate_email("  Ana@NovaSBE.pt  ") is None


@pytest.mark.parametrize("address", [
    "ana@gmail.com",
    "@novasbe.pt",
    "ana@sub.novasbe.pt",
    "ana@@novasbe.pt",
])
def test_r1_1_email_outside_the_club_domain_is_refused(address):
    refusal = accounts.validate_email(address)
    assert refusal is not None
    assert refusal.ok is False
    assert refusal.code is Code.INVALID


# --- R1.2 full name --------------------------------------------------------

@pytest.mark.parametrize("name", ["Jo", "A" * 60, "Joao D'Avila", "João D'Ávila", "Ana-Maria St."])
def test_r1_2_name_within_the_range_is_accepted(name):
    assert accounts.validate_name(name) is None


@pytest.mark.parametrize("name", ["J", "A" * 61, "Ana <script>", "Ana > Bruno"])
def test_r1_2_name_outside_the_range_or_with_markup_is_refused(name):
    refusal = accounts.validate_name(name)
    assert refusal is not None
    assert refusal.code is Code.INVALID


# --- R1.3 password ---------------------------------------------------------

def test_r1_3_password_of_eight_characters_is_accepted():
    assert accounts.validate_password("a" * 8) is None


def test_r1_3_password_of_seven_characters_is_refused():
    refusal = accounts.validate_password("a" * 7)
    assert refusal is not None
    assert refusal.code is Code.INVALID


def test_r1_3_confirmation_must_match():
    refusal = accounts.validate_password("a" * 8, "a" * 8 + "b")
    assert refusal is not None
    assert refusal.code is Code.INVALID


def test_r1_3_matching_confirmation_is_accepted():
    assert accounts.validate_password("a" * 8, "a" * 8) is None


def test_r1_3_refusal_never_repeats_the_password():
    secret = "hunter2-very-secret"
    refusal = accounts.validate_password(secret, secret + "x")
    assert secret not in refusal.message


# --- the auth wrapper ------------------------------------------------------

def test_sign_up_checks_the_domain_before_reaching_supabase():
    factory = CountingFactory()
    result = auth.sign_up("ana@gmail.com", GOOD_PASSWORD, "Ana Silva", client_factory=factory)
    assert result.ok is False
    assert result.code is Code.INVALID
    assert factory.calls == 0


def test_sign_up_with_a_club_address_reaches_supabase():
    factory = CountingFactory()
    result = auth.sign_up("ana@novasbe.pt", GOOD_PASSWORD, "Ana Silva", client_factory=factory)
    assert result.ok is True
    assert result.data["auth_user_id"] == "auth-uid-1"
    assert result.data["email"] == "ana@novasbe.pt"
    assert factory.calls == 1


def test_sign_up_reports_when_the_address_still_needs_confirming():
    factory = CountingFactory(confirmed=False)
    result = auth.sign_up("ana@novasbe.pt", GOOD_PASSWORD, "Ana Silva", client_factory=factory)
    assert result.ok is True
    assert result.data["needs_confirmation"] is True


def test_sign_in_with_a_failing_client_is_refused_without_saying_which_field():
    factory = CountingFactory(raises=True)
    result = auth.sign_in("ana@novasbe.pt", GOOD_PASSWORD, client_factory=factory)
    assert result.ok is False
    assert result.code is Code.INVALID
    assert result.message == "Email or password is wrong."


def test_sign_in_never_leaks_the_password_into_the_message():
    factory = CountingFactory(raises=True)
    result = auth.sign_in("ana@novasbe.pt", GOOD_PASSWORD, client_factory=factory)
    assert GOOD_PASSWORD not in result.message


def test_sign_in_builds_a_new_client_for_every_attempt():
    factory = CountingFactory()
    auth.sign_in("ana@novasbe.pt", GOOD_PASSWORD, client_factory=factory)
    auth.sign_in("ana@novasbe.pt", GOOD_PASSWORD, client_factory=factory)
    assert factory.calls == 2
    assert factory.clients[0] is not factory.clients[1]


def test_sign_in_normalises_the_address_before_sending_it():
    factory = CountingFactory()
    auth.sign_in("  Ana@NovaSBE.pt  ", GOOD_PASSWORD, client_factory=factory)
    assert factory.clients[0].seen_emails == ["ana@novasbe.pt"]
