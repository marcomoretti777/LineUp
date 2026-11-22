"""My bookings screen: upcoming bookings, waitlist places and booking history.

Every decision comes from lineup.services; this page only draws the lists and
hands each action to ui.run_action and ui.show_result.

Rules: section 11 (My bookings), LU06, R4.5, R4.6, R5.2.
"""

from __future__ import annotations

import streamlit as st

from lineup import ui
from lineup.models import Condition, Label, Role, SessionView
from lineup.services import booking, forecast
from lineup.timeutil import fmt_dt, fmt_time

# Session-state keys: the last action's Result survives the rerun that closes
# the dialog, and the Cancel click keeps the dialog open until it is finished
# or dismissed.
_RESULT_KEY = "my_bookings_result"
_CANCEL_KEY = "my_bookings_cancel"

_NO_UPCOMING = "You have no upcoming sessions."
_NO_PAST = "No past sessions yet."
_STAFF_ONLY = "My bookings is for students."
_NO_FORECAST = Condition(Label.UNKNOWN, None, None, "")

_OUTCOME_WORDS = {
    "attended": "Attended",
    "no_show": "No-show",
    "called_off": "Called off",
    "cancelled": "Cancelled",
    None: "Not marked yet",
}


def _when(session: SessionView) -> str:
    return f"{fmt_dt(session.starts_at)}–{fmt_time(session.ends_at)}"


def _who(session: SessionView) -> str:
    return f"{session.level.value.capitalize()} · {ui.plain(session.instructor_name)}"


def _close_dialog() -> None:
    st.session_state.pop(_CANCEL_KEY, None)


def _finish(result) -> None:
    # None means run_action already showed the error; a rerun would wipe it.
    if result is None:
        return
    _close_dialog()
    st.session_state[_RESULT_KEY] = result
    st.rerun()


@st.dialog("Cancel this booking", on_dismiss=_close_dialog)
def _cancel_dialog(engine, actor_id: int, item: booking.UpcomingBooking) -> None:
    st.markdown(f"**{_when(item.session)}**")
    st.caption(_who(item.session))
    preview = ui.run_action(booking.cancel_preview, engine, actor_id, item.booking_id)
    if preview is None:
        return
    if not preview.ok:
        ui.show_result(preview)
        return
    if preview.data["refund"]:
        st.info(preview.message)
    else:
        st.warning(preview.message)

    confirm_col, keep_col = st.columns(2)
    if keep_col.button("Keep booking", key="dialog_keep"):
        _close_dialog()
        st.rerun()
    if confirm_col.button("Confirm cancellation", type="primary", key="dialog_confirm"):
        result = ui.run_action(booking.cancel_booking, engine, actor_id, item.booking_id)
        if result is not None and result.ok:
            _finish(result)
        ui.show_result(result)


def _request_cancel(item: booking.UpcomingBooking) -> None:
    st.session_state[_CANCEL_KEY] = item


def _upcoming(engine, items: list[booking.UpcomingBooking]) -> None:
    conditions = ui.run_action(
        forecast.conditions_for_sessions, engine, [item.session for item in items]
    ) or {}
    for item in items:
        with st.container(border=True):
            st.markdown(f"**{_when(item.session)}**")
            st.caption(_who(item.session))
            ui.badge(conditions.get(item.session.id, _NO_FORECAST))
            st.caption(f"Free cancellation until {fmt_dt(item.free_cancel_until)}.")
            st.button("Cancel", key=f"cancel_{item.booking_id}",
                      on_click=_request_cancel, args=(item,))
    ui.footer_credit()


def _waiting(engine, actor_id: int, spots: list[booking.WaitingSpot]) -> None:
    for spot in spots:
        with st.container(border=True):
            st.markdown(f"**{_when(spot.session)}**")
            st.caption(_who(spot.session))
            st.markdown(f":blue-background[**Waitlist #{spot.position}**]")
            if st.button("Leave waitlist", key=f"leave_{spot.entry_id}"):
                _finish(ui.run_action(booking.leave_waitlist, engine, actor_id, spot.entry_id))


def _past(items: list[booking.PastBooking]) -> None:
    if not items:
        st.caption(_NO_PAST)
        return
    for item in items:
        refunded = "yes" if item.refunded else "no"
        st.markdown(
            f"**{fmt_dt(item.session.starts_at)}** · {_OUTCOME_WORDS.get(item.outcome)}"
            f" · Refunded: {refunded}"
        )


def main() -> None:
    """Draw the My bookings screen for the signed-in student.

    Rules: section 11 (My bookings), LU06, R4.5, R4.6, R5.2.
    """
    engine = ui.get_engine()
    actor = ui.current_actor(engine)
    if actor is None:
        st.stop()

    st.title("My bookings")
    if actor.role != Role.STUDENT:
        st.info(_STAFF_ONLY)
        return
    ui.show_result(st.session_state.pop(_RESULT_KEY, None))

    pending = st.session_state.get(_CANCEL_KEY)
    if pending:
        _cancel_dialog(engine, actor.id, pending)

    mine = ui.run_action(booking.list_my_bookings, engine, actor.id)
    if mine is None:
        return

    st.subheader("Upcoming")
    if mine.upcoming:
        _upcoming(engine, mine.upcoming)
    if mine.waiting:
        st.subheader("Waiting")
        _waiting(engine, actor.id, mine.waiting)
    if not mine.upcoming and not mine.waiting:
        st.info(_NO_UPCOMING)
        st.page_link("app_pages/sessions.py", label="Sessions", icon=":material/surfing:")

    st.subheader("Past")
    _past(mine.past)


main()
