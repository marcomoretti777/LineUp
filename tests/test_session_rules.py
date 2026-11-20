"""Pure session create, edit and delete rules (R2.1-R2.9, R2.11)."""

import importlib
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from lineup.models import MESSAGES, Code, Level, SessionStatus
from lineup.timeutil import from_local

TOMORROW = date(2026, 11, 21)


class _LazyRules:
    # Import on first attribute use, inside the test body, so a missing rule
    # reports as a test failure rather than a collection or fixture error.
    def __getattr__(self, name):
        return getattr(importlib.import_module("lineup.logic.sessions"), name)


@pytest.fixture
def rules():
    return _LazyRules()


def _local(hour, minute=0, day=TOMORROW):
    return from_local(day, time(hour, minute))


def _new(now, **overrides):
    # Baseline is a session every rule allows, so each test flips exactly one input.
    kwargs = dict(
        now=now,
        starts_at=_local(10),
        duration_min=90,
        capacity=4,
        level=Level.BEGINNER,
    )
    kwargs.update(overrides)
    return kwargs


def _current():
    return {
        "starts_at": _local(10),
        "duration_min": 90,
        "capacity": 4,
        "level": Level.BEGINNER,
    }


def _edit(now, **overrides):
    kwargs = dict(
        now=now,
        starts_at=_local(10),
        status=SessionStatus.SCHEDULED,
        confirmed_count=0,
        current=_current(),
        changes={},
    )
    kwargs.update(overrides)
    return kwargs


def _delete(now, **overrides):
    kwargs = dict(
        now=now,
        starts_at=_local(10),
        status=SessionStatus.SCHEDULED,
        ever_booked=False,
        ever_waited=False,
    )
    kwargs.update(overrides)
    return kwargs


def _assert_refused(result, code):
    assert result is not None
    assert result.ok is False
    assert result.code == code


# --- R2.1 start on a 15-minute step, at or after 08:00 local ---


def test_r2_1_start_before_0800_is_invalid(rules, now):
    result = rules.validate_new_session(**_new(now, starts_at=_local(7, 45)))
    _assert_refused(result, Code.INVALID)


def test_r2_1_start_at_0800_is_allowed(rules, now):
    assert rules.validate_new_session(**_new(now, starts_at=_local(8))) is None


def test_r2_1_start_off_15_minute_step_is_invalid(rules, now):
    result = rules.validate_new_session(**_new(now, starts_at=_local(8, 10)))
    _assert_refused(result, Code.INVALID)


def test_r2_1_uses_lisbon_time_in_summer(rules):
    # In summer Lisbon is UTC+1, so 08:00 local is 07:00 UTC: a raw-UTC check would get both wrong.
    june_now = datetime(2026, 6, 1, 9, 0)
    june_2 = date(2026, 6, 2)
    eight = from_local(june_2, time(8, 0))
    assert eight == datetime(2026, 6, 2, 7, 0)
    assert rules.validate_new_session(**_new(june_now, starts_at=eight)) is None
    early = from_local(june_2, time(7, 45))
    _assert_refused(rules.validate_new_session(**_new(june_now, starts_at=early)), Code.INVALID)


# --- R2.2 at least 3 hours ahead, at most 14 days ahead ---


def test_r2_2_start_2h59_after_now_is_invalid(rules, now):
    # Shift now by a minute so the start (12:00) sits on a 15-minute step and only R2.2 can fail.
    later_now = now + timedelta(minutes=1)
    starts_at = later_now + timedelta(hours=2, minutes=59)
    assert starts_at == datetime(2026, 11, 20, 12, 0)
    result = rules.validate_new_session(**_new(later_now, starts_at=starts_at))
    _assert_refused(result, Code.INVALID)
    assert "3 hours" in result.message


def test_r2_2_start_3h_after_now_is_allowed(rules, now):
    starts_at = now + timedelta(hours=3)
    assert rules.validate_new_session(**_new(now, starts_at=starts_at)) is None


def test_r2_2_today_plus_14_is_allowed(rules, now):
    starts_at = _local(10, day=date(2026, 11, 20) + timedelta(days=14))
    assert rules.validate_new_session(**_new(now, starts_at=starts_at)) is None


def test_r2_2_today_plus_15_is_invalid(rules, now):
    starts_at = _local(10, day=date(2026, 11, 20) + timedelta(days=15))
    result = rules.validate_new_session(**_new(now, starts_at=starts_at))
    _assert_refused(result, Code.INVALID)
    assert "14 days" in result.message


# --- R2.3 duration ---


@pytest.mark.parametrize("minutes", [45, 150])
def test_r2_3_duration_not_allowed_is_invalid(rules, now, minutes):
    result = rules.validate_new_session(**_new(now, duration_min=minutes))
    _assert_refused(result, Code.INVALID)


@pytest.mark.parametrize("minutes", [60, 90, 120])
def test_r2_3_allowed_durations(rules, now, minutes):
    assert rules.validate_new_session(**_new(now, duration_min=minutes)) is None


# --- R2.4 capacity ---


@pytest.mark.parametrize("capacity", [0, 9])
def test_r2_4_capacity_out_of_range_is_invalid(rules, now, capacity):
    result = rules.validate_new_session(**_new(now, capacity=capacity))
    _assert_refused(result, Code.INVALID)


@pytest.mark.parametrize("capacity", [1, 8])
def test_r2_4_capacity_bounds_allowed(rules, now, capacity):
    assert rules.validate_new_session(**_new(now, capacity=capacity)) is None


@pytest.mark.parametrize("capacity", [2.5, "4", True])
def test_r2_4_non_integer_capacity_is_invalid(rules, now, capacity):
    result = rules.validate_new_session(**_new(now, capacity=capacity))
    _assert_refused(result, Code.INVALID)


# --- R2.5 level ---


def test_r2_5_unknown_level_is_invalid(rules, now):
    result = rules.validate_new_session(**_new(now, level="expert"))
    _assert_refused(result, Code.INVALID)


@pytest.mark.parametrize("level", [Level.BEGINNER, "intermediate"])
def test_r2_5_known_levels_allowed(rules, now, level):
    assert rules.validate_new_session(**_new(now, level=level)) is None


# --- R2.6 instructor overlap ---


def _existing(status=SessionStatus.SCHEDULED):
    return [SimpleNamespace(starts_at=_local(10), duration_min=90, status=status)]


def test_r2_6_overlapping_start_is_clash(rules):
    assert rules.has_overlap(_local(11), 60, _existing()) is True


def test_r2_6_back_to_back_is_allowed(rules):
    assert rules.has_overlap(_local(11, 30), 60, _existing()) is False


def test_r2_6_called_off_session_does_not_count(rules):
    existing = _existing(status=SessionStatus.CALLED_OFF)
    assert rules.has_overlap(_local(11), 60, existing) is False


# --- R2.7 latest end (optional) ---


def test_r2_7_end_at_latest_end_is_allowed(rules, now):
    # Baseline ends 11:30 local.
    kwargs = _new(now, latest_end=_local(11, 30))
    assert rules.validate_new_session(**kwargs) is None


def test_r2_7_end_one_minute_after_latest_end_is_invalid(rules, now):
    kwargs = _new(now, latest_end=_local(11, 29))
    _assert_refused(rules.validate_new_session(**kwargs), Code.INVALID)


def test_r2_7_no_latest_end_means_no_check(rules, now):
    kwargs = _new(now, starts_at=_local(16), duration_min=120, latest_end=None)
    assert rules.validate_new_session(**kwargs) is None


# --- R2.8 edits only before the start of a scheduled session ---


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(minutes=1)])
def test_r2_8_edit_at_or_after_start_is_closed(rules, now, offset):
    starts_at = now - offset
    current = dict(_current(), starts_at=starts_at)
    result = rules.check_edit(
        **_edit(now, starts_at=starts_at, current=current, changes={"capacity": 5})
    )
    _assert_refused(result, Code.CLOSED)


def test_r2_8_edit_called_off_session_is_closed(rules, now):
    result = rules.check_edit(
        **_edit(now, status=SessionStatus.CALLED_OFF, changes={"capacity": 5})
    )
    _assert_refused(result, Code.CLOSED)


# --- R2.9 what may change ---


@pytest.mark.parametrize(
    "changes",
    [{"starts_at": _local(12)}, {"duration_min": 60}, {"level": Level.INTERMEDIATE}],
    ids=["start", "duration", "level"],
)
def test_r2_9_with_bookings_changing_start_duration_or_level_is_invalid(rules, now, changes):
    result = rules.check_edit(**_edit(now, confirmed_count=1, changes=changes))
    _assert_refused(result, Code.INVALID)


def test_r2_9_with_bookings_capacity_up_is_allowed(rules, now):
    assert rules.check_edit(**_edit(now, confirmed_count=1, changes={"capacity": 6})) is None


def test_r2_9_with_bookings_capacity_down_is_invalid(rules, now):
    result = rules.check_edit(**_edit(now, confirmed_count=1, changes={"capacity": 3}))
    _assert_refused(result, Code.INVALID)


def test_r2_9_with_bookings_capacity_above_8_is_invalid(rules, now):
    result = rules.check_edit(**_edit(now, confirmed_count=1, changes={"capacity": 9}))
    _assert_refused(result, Code.INVALID)


def test_r2_9_with_bookings_unchanged_value_is_not_a_change(rules, now):
    # Edit forms resubmit every field; repeating the current start is not a time change.
    changes = {"starts_at": _local(10), "capacity": 6}
    assert rules.check_edit(**_edit(now, confirmed_count=1, changes=changes)) is None


def test_r2_9_no_bookings_any_field_may_change(rules, now):
    changes = {
        "starts_at": _local(14),
        "duration_min": 120,
        "capacity": 2,
        "level": Level.INTERMEDIATE,
    }
    assert rules.check_edit(**_edit(now, changes=changes)) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"starts_at": _local(7, 45)},
        {"duration_min": 45},
        {"capacity": 9},
        {"level": "expert"},
    ],
    ids=["start", "duration", "capacity", "level"],
)
def test_r2_9_no_bookings_changes_still_validated(rules, now, changes):
    _assert_refused(rules.check_edit(**_edit(now, changes=changes)), Code.INVALID)


# --- R2.11 delete ---


@pytest.mark.parametrize(
    "flags",
    [{"ever_booked": True}, {"ever_waited": True}],
    ids=["booked", "waited"],
)
def test_r2_11_ever_booked_or_ever_waited_is_invalid(rules, now, flags):
    _assert_refused(rules.check_delete(**_delete(now, **flags)), Code.INVALID)


def test_r2_11_never_booked_or_waited_is_allowed(rules, now):
    assert rules.check_delete(**_delete(now)) is None


def test_r2_11_delete_after_start_is_closed(rules, now):
    result = rules.check_delete(**_delete(now, starts_at=now, ever_booked=True))
    _assert_refused(result, Code.CLOSED)


def test_r2_11_delete_called_off_session_is_closed(rules, now):
    result = rules.check_delete(**_delete(now, status=SessionStatus.CALLED_OFF))
    _assert_refused(result, Code.CLOSED)


# --- Refusal messages ---


@pytest.mark.parametrize(
    "overrides, field, allowed",
    [
        ({"starts_at": _local(7, 45)}, "Start time", "08:00"),
        ({"duration_min": 45}, "Duration", "60, 90 or 120"),
        ({"capacity": 9}, "Capacity", "1 to 8"),
        ({"level": "expert"}, "Level", "Beginner or Intermediate"),
    ],
    ids=["start", "duration", "capacity", "level"],
)
def test_r2_refusal_messages_name_field_and_allowed_range(rules, now, overrides, field, allowed):
    result = rules.validate_new_session(**_new(now, **overrides))
    _assert_refused(result, Code.INVALID)
    assert result.message.startswith(field)
    assert allowed in result.message
    assert "{" not in result.message


def test_r2_8_closed_message_comes_from_catalogue(rules, now):
    result = rules.check_edit(**_edit(now, status=SessionStatus.CALLED_OFF))
    _assert_refused(result, Code.CLOSED)
    assert result.message.startswith(MESSAGES[Code.CLOSED].split("{")[0])
