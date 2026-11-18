"""Tests for the notifications service: inbox listing and read state (R11.2-R11.3)."""

import pytest

from lineup import db
from lineup.services.notifications import list_notifications, mark_all_read, unread


def _field(item, name):
    """Read a field from a notification whether it is a dict or an object."""
    if isinstance(item, dict):
        return item[name]
    return getattr(item, name)


def _messages(result):
    return [_field(n, "message") for n in result.data]


def _notify_many(engine, member_id, messages, kind="info"):
    with engine.begin() as conn:
        for msg in messages:
            db.notify(conn, member_id, kind, msg)


def _unread_count(engine, member_id):
    with engine.begin() as conn:
        return db.unread_count(conn, member_id)


# ---------- inbox listing ----------

def test_list_returns_only_actor_notifications_newest_first(engine, make_member):
    a = make_member(engine)
    b = make_member(engine)
    _notify_many(engine, a, ["A-1", "A-2", "A-3"])
    _notify_many(engine, b, ["B-1", "B-2"])

    result = list_notifications(engine, a)

    assert result.ok
    assert _messages(result) == ["A-3", "A-2", "A-1"]


def test_list_caps_at_50(engine, make_member):
    a = make_member(engine)
    _notify_many(engine, a, [f"A-{i}" for i in range(1, 56)])

    result = list_notifications(engine, a)

    assert result.ok
    assert len(result.data) == 50
    assert _messages(result)[0] == "A-55"
    assert _messages(result)[-1] == "A-6"


def test_list_empty_inbox_ok(engine, make_member):
    a = make_member(engine)

    result = list_notifications(engine, a)

    assert result.ok
    assert list(result.data) == []


# ---------- read state ----------

def test_unread_returns_actor_count(engine, make_member):
    a = make_member(engine)
    b = make_member(engine)
    _notify_many(engine, a, ["A-1", "A-2", "A-3"])
    _notify_many(engine, b, ["B-1", "B-2"])

    result_a = unread(engine, a)
    result_b = unread(engine, b)

    assert result_a.ok
    assert result_a.data == 3
    assert result_b.ok
    assert result_b.data == 2


def test_mark_all_read_only_touches_actor(engine, make_member, now):
    a = make_member(engine)
    b = make_member(engine)
    _notify_many(engine, a, ["A-1", "A-2", "A-3"])
    _notify_many(engine, b, ["B-1", "B-2"])

    result = mark_all_read(engine, a, now=now)

    assert result.ok
    assert _unread_count(engine, a) == 0
    assert unread(engine, a).data == 0
    for n in list_notifications(engine, a).data:
        assert _field(n, "read_at") is not None
    assert _unread_count(engine, b) == 2
    for n in list_notifications(engine, b).data:
        assert _field(n, "read_at") is None


# ---------- R11.2 notify is part of the caller's transaction ----------

def test_r11_2_notify_rolls_back_on_exception(engine, make_member):
    a = make_member(engine)

    with pytest.raises(RuntimeError):
        with engine.begin() as conn:
            db.notify(conn, a, "info", "should vanish")
            raise RuntimeError("boom")

    assert _unread_count(engine, a) == 0
    assert list(list_notifications(engine, a).data) == []


# ---------- R11.3 members never see each other's notifications ----------

def test_r11_3_list_as_b_never_includes_a_when_b_empty(engine, make_member):
    a = make_member(engine)
    b = make_member(engine)
    _notify_many(engine, a, ["A-secret-1", "A-secret-2"])

    result = list_notifications(engine, b)

    assert result.ok
    assert list(result.data) == []


def test_r11_3_list_as_b_never_includes_a_when_both_have_some(engine, make_member):
    a = make_member(engine)
    b = make_member(engine)
    _notify_many(engine, a, ["A-secret-1", "A-secret-2"])
    _notify_many(engine, b, ["B-own-1"])
    _notify_many(engine, a, ["A-secret-3"])

    result = list_notifications(engine, b)

    assert result.ok
    assert _messages(result) == ["B-own-1"]
    assert not any(m.startswith("A-") for m in _messages(result))
