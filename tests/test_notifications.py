"""Tests for the notifications service: inbox listing and read state (R11.2-R11.3)."""

import pytest
from conftest import make_member

from lineup import db
from lineup.models import Code
from lineup.services.notifications import list_notifications, mark_all_read, unread


def _messages(result):
    return [n["message"] for n in result.data]


def _notify_many(engine, member_id, messages, kind="info"):
    with engine.begin() as conn:
        for msg in messages:
            db.notify(conn, member_id, kind, msg)


def _unread_count(engine, member_id):
    with engine.connect() as conn:
        return db.unread_count(conn, member_id)


def test_r11_3_list_returns_only_own_newest_first(engine):
    a = make_member(engine)
    b = make_member(engine)
    _notify_many(engine, a, ["A-1", "A-2", "A-3"])
    _notify_many(engine, b, ["B-1", "B-2"])

    result = list_notifications(engine, a)

    assert result.ok
    assert _messages(result) == ["A-3", "A-2", "A-1"]


def test_r11_3_list_caps_at_50_newest(engine):
    a = make_member(engine)
    _notify_many(engine, a, [f"A-{i}" for i in range(1, 56)])

    result = list_notifications(engine, a)

    assert result.ok
    assert len(result.data) == 50
    assert _messages(result)[0] == "A-55"
    assert _messages(result)[-1] == "A-6"


def test_r11_3_list_empty_inbox_ok(engine):
    a = make_member(engine)

    result = list_notifications(engine, a)

    assert result.ok
    assert result.data == []


def test_r11_3_unread_counts_only_own(engine):
    a = make_member(engine)
    b = make_member(engine)
    _notify_many(engine, a, ["A-1", "A-2", "A-3"])
    _notify_many(engine, b, ["B-1", "B-2"])

    assert unread(engine, a).data == 3
    assert unread(engine, b).data == 2


def test_r11_3_mark_all_read_touches_only_own(engine, now):
    a = make_member(engine)
    b = make_member(engine, role="instructor")
    _notify_many(engine, a, ["A-1", "A-2", "A-3"])
    _notify_many(engine, b, ["B-1", "B-2"])

    result = mark_all_read(engine, a, now=now)

    assert result.ok
    assert unread(engine, a).data == 0
    assert all(n["read_at"] == now for n in list_notifications(engine, a).data)
    assert _unread_count(engine, b) == 2
    assert all(n["read_at"] is None for n in list_notifications(engine, b).data)


def test_r11_3_list_as_b_never_includes_a(engine):
    a = make_member(engine)
    b = make_member(engine)
    _notify_many(engine, a, ["A-secret-1", "A-secret-2"])
    assert list_notifications(engine, b).data == []

    _notify_many(engine, b, ["B-own-1"])
    _notify_many(engine, a, ["A-secret-3"])

    assert _messages(list_notifications(engine, b)) == ["B-own-1"]


def test_r11_3_unknown_actor_not_found(engine, now):
    for result in (list_notifications(engine, 9999), unread(engine, 9999),
                   mark_all_read(engine, 9999, now=now)):
        assert not result.ok
        assert result.code == Code.NOT_FOUND


def test_r11_2_notify_rolls_back_with_failed_action(engine):
    a = make_member(engine)

    with pytest.raises(RuntimeError):
        with engine.begin() as conn:
            db.notify(conn, a, "info", "should vanish")
            raise RuntimeError("boom")

    assert _unread_count(engine, a) == 0
    assert list_notifications(engine, a).data == []
