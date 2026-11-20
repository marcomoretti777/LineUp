"""Tests for the shared types, configuration and time helpers.

Modules are imported inside each test so that, before the feature exists,
every test fails on its own instead of the whole file failing to collect.
"""

import importlib
from datetime import date, datetime, time, timedelta

import pytest

NOW = datetime(2026, 11, 20, 9, 0)


def models():
    return importlib.import_module("lineup.models")


def config():
    return importlib.import_module("lineup.config")


def timeutil():
    return importlib.import_module("lineup.timeutil")


# ---- Result and message catalogue (spec sections 8 and 11) ----


def test_section8_result_success_sets_ok_and_no_code():
    m = models()
    result = m.Result.success("Booked", data={"id": 7})
    assert result.ok is True
    assert result.code is None
    assert result.message == "Booked"
    assert result.data == {"id": 7}


def test_section8_result_fail_sets_code_and_keeps_data():
    m = models()
    result = m.Result.fail(m.Code.FULL, "Full", data={"session_id": 3})
    assert result.ok is False
    assert result.code is m.Code.FULL
    assert result.message == "Full"
    assert result.data == {"session_id": 3}


def test_section8_result_is_immutable():
    m = models()
    result = m.Result.success("Done")
    with pytest.raises(AttributeError):
        result.ok = False


def test_section5_codes_match_the_spec_list():
    m = models()
    assert {c.value for c in m.Code} == {
        "forbidden", "invalid", "not_found", "closed", "not_yet", "no_credits",
        "clash", "level", "duplicate", "full", "not_full", "already_done",
    }


def test_section11_every_code_has_a_message_template():
    m = models()
    assert set(m.MESSAGES) == set(m.Code)
    assert all(m.MESSAGES[code].strip() for code in m.Code)


def test_section11_fill_clash_puts_the_time_in_the_text():
    m = models()
    text = m.fill(m.Code.CLASH, time="10:00")
    assert text == "You already have a session at that time (10:00)."


def test_section11_fill_invalid_uses_field_problem_and_allowed():
    m = models()
    text = m.fill(m.Code.INVALID, field="Capacity", problem="9 is too many", allowed="1 to 8")
    assert text == "Capacity: 9 is too many. Allowed: 1 to 8."


def test_section11_fill_is_strict_about_missing_placeholders():
    m = models()
    with pytest.raises(KeyError):
        m.fill(m.Code.INVALID, field="Capacity")


def test_section11_fill_without_placeholders_returns_the_template():
    m = models()
    assert m.fill(m.Code.FORBIDDEN) == "You don't have permission to do that."


@pytest.mark.parametrize(
    "enum_name, values",
    [
        ("Role", {"student", "instructor", "admin"}),
        ("Level", {"beginner", "intermediate"}),
        ("SessionStatus", {"scheduled", "called_off"}),
        ("BookingStatus", {"confirmed", "cancelled", "called_off"}),
        ("Attendance", {"attended", "no_show"}),
        ("WaitStatus", {"waiting", "promoted", "left", "removed", "cleared"}),
        ("RequestStatus", {"pending", "approved", "rejected", "withdrawn"}),
        ("LedgerKind", {"purchase", "booking", "refund"}),
        ("CallOffCategory", {"conditions", "instructor_unavailable", "other"}),
        ("Label", {"go", "marginal", "no_go", "unknown"}),
    ],
)
def test_section9_enum_values_match_the_data_model(enum_name, values):
    enum = getattr(models(), enum_name)
    assert {member.value for member in enum} == values


def test_section8_session_view_ends_at_is_start_plus_duration():
    m = models()
    view = m.SessionView(
        id=1, instructor_id=2, instructor_name="Tiago Costa",
        starts_at=datetime(2026, 11, 21, 10, 0), duration_min=90,
        level=m.Level.BEGINNER, capacity=4, booked_count=2,
        status=m.SessionStatus.SCHEDULED,
    )
    assert view.ends_at == datetime(2026, 11, 21, 11, 30)


# ---- Configuration (spec section 5, R1.7) ----


def test_section5_config_constants_match_the_spec():
    c = config()
    assert c.TIMEZONE == "Europe/Lisbon"
    assert (c.LATITUDE, c.LONGITUDE) == (38.68, -9.34)
    assert c.BOOKING_CUTOFF == timedelta(hours=2)
    assert c.REFUND_WINDOW == timedelta(hours=24)
    assert c.MIN_LEAD == timedelta(hours=3)
    assert c.MAX_DAYS_AHEAD == 14
    assert c.DURATIONS == (60, 90, 120)
    assert (c.CAPACITY_MIN, c.CAPACITY_MAX) == (1, 8)
    assert c.EARLIEST_START == time(8, 0)
    assert c.FALLBACK_LATEST_END == time(17, 0)
    assert c.START_STEP_MIN == 15
    assert c.ALLOWED_EMAIL_DOMAIN == "novasbe.pt"


def test_r7_forecast_timings_match_the_spec():
    c = config()
    assert c.FORECAST_REFRESH == timedelta(minutes=60)
    assert c.FORECAST_RETRY == timedelta(minutes=10)
    assert c.FORECAST_STALE == timedelta(hours=12)
    assert c.HTTP_TIMEOUT_S == 5


def test_r10_1_credit_packs_match_the_spec():
    assert config().CREDIT_PACKS == [
        ("1 session", 1, 1500),
        ("5 sessions", 5, 6500),
        ("10 sessions", 10, 12000),
    ]


def test_r6_default_thresholds_match_the_spec():
    assert config().DEFAULT_THRESHOLDS == {
        "beginner": (1.5, 25, 2.0, 35),
        "intermediate": (2.5, 30, 3.0, 40),
    }


@pytest.mark.parametrize(
    "database_url, supabase_url, allowed",
    [
        (None, None, True),
        ("", "", True),
        ("sqlite:///data/lineup.db", None, True),
        ("postgresql+psycopg://user:pw@host:5432/postgres", None, False),
        (None, "https://example.supabase.co", False),
        ("sqlite:///data/lineup.db", "https://example.supabase.co", False),
    ],
)
def test_r1_7_demo_mode_only_on_local_sqlite_without_supabase(database_url, supabase_url, allowed):
    assert config().demo_mode_allowed(database_url, supabase_url) is allowed


def test_section12_get_secret_reads_the_environment_first(monkeypatch):
    monkeypatch.setenv("LINEUP_TEST_SETTING", "from-env")
    assert config().get_secret("LINEUP_TEST_SETTING") == "from-env"


def test_section12_get_secret_returns_none_when_missing(monkeypatch):
    monkeypatch.delenv("LINEUP_TEST_MISSING", raising=False)
    assert config().get_secret("LINEUP_TEST_MISSING") is None


# ---- Time helpers (spec section 8: naive UTC in the database, Lisbon on screen) ----


def test_section8_utcnow_is_naive_utc():
    now = timeutil().utcnow()
    assert now.tzinfo is None


def test_section8_to_local_in_november_equals_utc():
    local = timeutil().to_local(datetime(2026, 11, 20, 10, 0))
    assert (local.hour, local.minute) == (10, 0)
    assert local.tzinfo is not None


def test_section8_to_local_in_july_is_one_hour_ahead():
    local = timeutil().to_local(datetime(2026, 7, 20, 10, 0))
    assert (local.hour, local.minute) == (11, 0)


def test_section8_from_local_returns_naive_utc_in_summer():
    assert timeutil().from_local(date(2026, 7, 20), time(11, 0)) == datetime(2026, 7, 20, 10, 0)


@pytest.mark.parametrize("day", [date(2026, 11, 20), date(2026, 7, 20)])
def test_section8_from_local_then_to_local_round_trips(day):
    t = timeutil()
    stored = t.from_local(day, time(10, 30))
    assert stored.tzinfo is None
    local = t.to_local(stored)
    assert (local.date(), local.time().replace(tzinfo=None)) == (day, time(10, 30))


def test_section8_local_date_uses_lisbon_time():
    assert timeutil().local_date(datetime(2026, 7, 20, 23, 30)) == date(2026, 7, 21)


def test_section8_floor_hour_drops_minutes():
    assert timeutil().floor_hour(datetime(2026, 11, 20, 10, 47, 12)) == datetime(2026, 11, 20, 10, 0)


def test_section11_fmt_dt_shows_weekday_day_month_and_time():
    assert timeutil().fmt_dt(datetime(2026, 11, 20, 10, 0)) == "Fri 20 Nov, 10:00"


def test_section11_fmt_dt_drops_the_leading_zero_of_the_day():
    assert timeutil().fmt_dt(datetime(2026, 11, 5, 10, 0)) == "Thu 5 Nov, 10:00"


def test_section11_fmt_time_shows_lisbon_hours_and_minutes():
    t = timeutil()
    assert t.fmt_time(datetime(2026, 11, 20, 10, 0)) == "10:00"
    assert t.fmt_time(datetime(2026, 7, 20, 10, 0)) == "11:00"
