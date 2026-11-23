"""Sessions screen: browse the next 14 days, book a place, join a waitlist.

Every decision comes from lineup.services; this page only draws the cards and
hands each action to ui.run_action and ui.show_result.

Rules: section 11 (Sessions), LU03, LU04, LU05, R3.10.
"""

from __future__ import annotations

import streamlit as st

from lineup import ui
from lineup.models import Code, Condition, Label, Level, Role, SessionView
from lineup.services import booking
from lineup.timeutil import fmt_dt, fmt_time

# Session-state keys: the last action's Result survives the rerun that closes
# the dialog, the Book click keeps the dialog open until it is finished or
# dismissed, and a FULL answer keeps the dialog's Join waitlist button.
_RESULT_KEY = "sessions_result"
_BOOK_KEY = "sessions_book"
_FULL_KEY = "sessions_dialog_full"
_OPEN_KEY = "sessions_open_dialog"

_LEVELS = {"All": None, "Beginner": Level.BEGINNER, "Intermediate": Level.INTERMEDIATE}
_NO_SESSIONS = "No sessions in the next 14 days yet."
_NO_MATCH = "No sessions match these filters."
_NO_FORECAST = Condition(Label.UNKNOWN, None, None, "")


def _when(session: SessionView) -> str:
    return f"{fmt_dt(session.starts_at)}–{fmt_time(session.ends_at)}"


def _places(card: booking.SessionCard) -> str:
    left = card.session.capacity - card.session.booked_count
    if left > 0:
        return f"{left} of {card.session.capacity} places left"
    return f"Full, {card.waiting_count} waiting"


def _status_text(status: booking.MyStatus) -> str | None:
    if status == "booked":
        return "Booked"
    if isinstance(status, tuple):
        return f"Waitlist #{status[1]}"
    return None


def _close_dialog() -> None:
    st.session_state.pop(_BOOK_KEY, None)
    st.session_state.pop(_FULL_KEY, None)


def _finish(result) -> None:
    # None means run_action already showed the error; a rerun would wipe it.
    if result is None:
        return
    _close_dialog()
    st.session_state[_RESULT_KEY] = result
    st.rerun()


@st.dialog("Book this session", on_dismiss=_close_dialog)
def _book_dialog(engine, actor_id: int, card: booking.SessionCard,
                 condition: Condition) -> None:
    session = card.session
    st.markdown(f"### {_when(session)}")
    ui.chip(session.level.value.capitalize(), "info")
    st.caption(f":material/person: {ui.plain(session.instructor_name)}")
    st.write(f"Uses 1 credit. Free cancellation until {fmt_dt(card.free_cancel_until)}.")
    ui.badge(condition)
    warning = booking.call_off_warning(condition)
    if warning:
        st.warning(warning)

    full = st.session_state.get(_FULL_KEY)
    if full is None or full[0] != session.id:
        confirm_col, cancel_col = st.columns(2)
        if cancel_col.button("Cancel", key="dialog_cancel"):
            _close_dialog()
            st.rerun()
        if confirm_col.button("Confirm", type="primary", key="dialog_confirm"):
            result = ui.run_action(booking.book, engine, actor_id, session.id)
            if result is not None and result.ok:
                _finish(result)
            if result is not None and result.code == Code.FULL:
                # Redraw only the dialog, now offering the waitlist instead.
                st.session_state[_FULL_KEY] = (session.id, result)
                st.rerun(scope="fragment")
            ui.show_result(result)
    else:
        ui.show_result(full[1])
        if st.button("Join waitlist", type="primary", key="dialog_join"):
            _finish(ui.run_action(booking.join_waitlist, engine, actor_id, session.id))


def _request_book(card: booking.SessionCard, condition: Condition) -> None:
    # A callback, so the click counts even if the refreshed card no longer
    # draws a Book button: the dialog then answers "just filled up".
    st.session_state[_BOOK_KEY] = (card, condition)
    st.session_state.pop(_FULL_KEY, None)
    st.session_state[_OPEN_KEY] = True


def _actions(engine, actor_id: int, card: booking.SessionCard, condition: Condition) -> None:
    session = card.session
    if card.book_block:
        st.button(card.book_block, disabled=True, key=f"blocked_{session.id}",
                  width="stretch")
    elif session.booked_count >= session.capacity:
        if st.button("Join waitlist", key=f"join_{session.id}", width="stretch"):
            _finish(ui.run_action(booking.join_waitlist, engine, actor_id, session.id))
    else:
        st.button("Book", type="primary", key=f"book_{session.id}", width="stretch",
                  on_click=_request_book, args=(card, condition))


def _card(engine, actor, card: booking.SessionCard, condition: Condition) -> None:
    # Decision order: when, who and what level, how many places, conditions,
    # what it costs, then the action.
    session = card.session
    with ui.card():
        st.markdown(f"### {_when(session)}")
        level_col, status_col = st.columns([1, 1])
        with level_col:
            ui.chip(session.level.value.capitalize(), "info")
        status = _status_text(card.my_status)
        if status:
            with status_col:
                ui.chip(status, "good" if status == "Booked" else "info")
        st.caption(f":material/person: {ui.plain(session.instructor_name)}")
        st.write(_places(card))
        ui.badge(condition)
        if actor.role == Role.STUDENT:
            st.caption("Uses 1 credit")
            _actions(engine, actor.id, card, condition)


@st.fragment(run_every="10s")
def _cards(engine, actor, level: Level | None, only_bookable: bool) -> None:
    """Draw the session cards, re-read every ten seconds so places left stay current.

    Rules: LU03, R6.
    """
    if st.session_state.pop(_OPEN_KEY, False):
        # The dialog opens on a full rerun, outside this fragment, so the
        # 10-second refresh never closes it mid-booking.
        st.rerun()
    cards = ui.run_action(booking.session_cards, engine, actor.id)
    if cards is None:
        return
    if not cards:
        ui.empty_state(_NO_SESSIONS)
        return
    conditions = ui.run_action(
        ui.cached_conditions, engine, [card.session for card in cards]
    ) or {}
    shown = [
        card for card in cards
        if (level is None or card.session.level == level)
        and (not only_bookable or card.can_book)
    ]
    if not shown:
        ui.empty_state(_NO_MATCH, ":material/filter_alt_off:")
        return
    for card in shown:
        _card(engine, actor, card, conditions.get(card.session.id, _NO_FORECAST))


def main() -> None:
    """Draw the Sessions screen for the signed-in member.

    Rules: section 11 (Sessions), LU03, LU04, LU05.
    """
    engine = ui.get_engine()
    ui.inject_styles()
    actor = ui.current_actor(engine)
    if actor is None:
        st.stop()
    student = actor.role == Role.STUDENT

    ui.page_header("Sessions", "The next 14 days at the spot.")
    ui.show_result(st.session_state.pop(_RESULT_KEY, None))

    level_col, toggle_col = st.columns([3, 2], vertical_alignment="bottom")
    with level_col:
        level_name = st.segmented_control(
            "Level", list(_LEVELS), default="All", key="sessions_level"
        ) or "All"
    only_bookable = False
    if student:
        with toggle_col:
            only_bookable = st.toggle("Only sessions I can book", key="sessions_only_bookable")

    pending = st.session_state.get(_BOOK_KEY)
    if pending and student:
        _book_dialog(engine, actor.id, *pending)

    _cards(engine, actor, _LEVELS[level_name], only_bookable)
    ui.footer_credit()


main()
