"""My sessions screen: sessions needing a decision, the create form, and own sessions.

Every decision comes from lineup.services; this page only draws the lists and
hands each action to ui.run_action and ui.show_result.

Rules: section 11 (My sessions), LU07, LU09, R2, R8.
"""

from __future__ import annotations

from datetime import time, timedelta

import streamlit as st

from lineup import config, ui
from lineup.models import CallOffCategory, Condition, Label, Level, Role, SessionStatus, SessionView
from lineup.services import forecast, sessions
from lineup.timeutil import fmt_dt, fmt_time, local_date, to_local, utcnow

# Session-state keys: the last action's Result survives the rerun that closes
# a dialog, and the clicked session keeps its dialog open until it is
# finished or dismissed.
_RESULT_KEY = "my_sessions_result"
_CALL_OFF_KEY = "my_sessions_call_off"
_EDIT_KEY = "my_sessions_edit"
_DELETE_KEY = "my_sessions_delete"
_DIALOG_KEYS = (_CALL_OFF_KEY, _EDIT_KEY, _DELETE_KEY)

_INSTRUCTORS_ONLY = "My sessions is for instructors."
_NO_DECISIONS = "Nothing needs your decision in the next 72 hours."
_NO_UPCOMING = "You have no upcoming sessions. Create one above."
_NO_FORECAST = Condition(Label.UNKNOWN, None, None, "")
_DEFAULT_START = time(10, 0)
_STEP_S = config.START_STEP_MIN * 60

_CATEGORY_LABELS = {
    CallOffCategory.CONDITIONS: "Conditions",
    CallOffCategory.INSTRUCTOR_UNAVAILABLE: "Instructor unavailable",
    CallOffCategory.OTHER: "Other",
}


def _when(session: SessionView) -> str:
    return f"{fmt_dt(session.starts_at)}–{fmt_time(session.ends_at)}"


def _booked(session: SessionView) -> str:
    return f"{session.booked_count}/{session.capacity} booked"


def _close_dialogs() -> None:
    for key in _DIALOG_KEYS:
        st.session_state.pop(key, None)


def _finish(result) -> None:
    # Only a success closes the dialog; a refusal stays on screen beside the
    # inputs so the instructor can fix them.
    if result is None or not result.ok:
        ui.show_result(result)
        return
    _close_dialogs()
    st.session_state[_RESULT_KEY] = result
    st.rerun()


def _open(key: str, session: SessionView) -> None:
    _close_dialogs()
    st.session_state[key] = session


@st.dialog("Call off this session", on_dismiss=_close_dialogs)
def _call_off_dialog(engine, actor_id: int, session: SessionView) -> None:
    st.markdown(f"**{_when(session)}**")
    category = st.selectbox(
        "Category", options=list(_CATEGORY_LABELS), format_func=_CATEGORY_LABELS.get,
        key=f"call_off_category_{session.id}",
    )
    reason = st.text_area(
        "Reason", max_chars=sessions.REASON_MAX, key=f"call_off_reason_{session.id}",
        help=f"{sessions.REASON_MIN}–{sessions.REASON_MAX} characters, sent to every student.",
    )
    n = session.booked_count
    st.warning(f"**{n} {'student' if n == 1 else 'students'} will be refunded and notified.**")
    st.caption("Anyone on the waitlist is told too, and the waitlist is cleared.")

    confirm_col, keep_col = st.columns(2)
    if keep_col.button("Keep session", key=f"call_off_keep_{session.id}"):
        _close_dialogs()
        st.rerun()
    if confirm_col.button("Confirm call-off", type="primary", key=f"call_off_confirm_{session.id}"):
        _finish(ui.run_action(
            sessions.call_off, engine, actor_id, session.id, category.value, reason,
        ))


def _day_bounds():
    today = local_date(utcnow())
    return today, today + timedelta(days=config.MAX_DAYS_AHEAD)


@st.dialog("Edit this session", on_dismiss=_close_dialogs)
def _edit_dialog(engine, actor_id: int, session: SessionView) -> None:
    st.markdown(f"**{_when(session)}**")
    if session.booked_count > 0:
        st.info("People are booked, so only capacity can change, and only upwards.")
        capacity = st.number_input(
            "Capacity", min_value=session.capacity, max_value=config.CAPACITY_MAX,
            value=session.capacity, step=1, key=f"edit_capacity_{session.id}",
        )
        changes = {"capacity": int(capacity)} if capacity != session.capacity else {}
    else:
        local = to_local(session.starts_at)
        first, last = _day_bounds()
        current = {
            "day": local.date(), "start_time": local.time().replace(tzinfo=None),
            "duration_min": session.duration_min, "capacity": session.capacity,
            "level": session.level,
        }
        proposed = {
            "day": st.date_input(
                "Date", value=min(max(current["day"], first), last),
                min_value=first, max_value=last, key=f"edit_day_{session.id}",
            ),
            "start_time": st.time_input(
                "Start", value=current["start_time"], step=_STEP_S, key=f"edit_start_{session.id}",
            ),
            "duration_min": st.selectbox(
                "Duration (minutes)", options=list(config.DURATIONS),
                index=list(config.DURATIONS).index(session.duration_min)
                if session.duration_min in config.DURATIONS else 0,
                key=f"edit_duration_{session.id}",
            ),
            "capacity": int(st.number_input(
                "Capacity", min_value=config.CAPACITY_MIN, max_value=config.CAPACITY_MAX,
                value=session.capacity, step=1, key=f"edit_capacity_{session.id}",
            )),
            "level": st.selectbox(
                "Level", options=list(Level), index=list(Level).index(session.level),
                format_func=lambda lvl: lvl.value.capitalize(), key=f"edit_level_{session.id}",
            ),
        }
        # Only changed fields go to the service, so unchanged ones are never re-checked.
        changes = {k: v for k, v in proposed.items() if v != current[k]}
        if "level" in changes:
            changes["level"] = changes["level"].value

    if st.button("Save changes", type="primary", key=f"edit_save_{session.id}", disabled=not changes):
        _finish(ui.run_action(sessions.edit_session, engine, actor_id, session.id, changes))


@st.dialog("Delete this session", on_dismiss=_close_dialogs)
def _delete_dialog(engine, actor_id: int, session: SessionView) -> None:
    st.markdown(f"**{_when(session)}**")
    st.warning("This session will be removed for good. Nobody has booked it.")
    confirm_col, keep_col = st.columns(2)
    if keep_col.button("Keep session", key=f"delete_keep_{session.id}"):
        _close_dialogs()
        st.rerun()
    if confirm_col.button("Delete session", type="primary", key=f"delete_confirm_{session.id}"):
        _finish(ui.run_action(sessions.delete_session, engine, actor_id, session.id))


def _decisions(engine, actor_id: int) -> None:
    st.subheader("Needs your decision")
    result = ui.run_action(sessions.decision_needed, engine, actor_id)
    if result is None:
        return
    if not result.ok:
        ui.show_result(result)
        return
    if not result.data:
        st.caption(_NO_DECISIONS)
        return
    for session, condition in result.data:
        with ui.card():
            st.markdown(f"### {_when(session)}")
            ui.badge(condition)
            st.caption(f":material/groups: {_booked(session)}")
            call_col, roster_col = st.columns(2)
            call_col.button("Call off", key=f"decide_call_off_{session.id}",
                            type="primary", width="stretch",
                            on_click=_open, args=(_CALL_OFF_KEY, session))
            with roster_col:
                st.page_link("app_pages/roster.py", label="Roster", icon=":material/group:",
                             query_params={"session": str(session.id)})


def _create_form(engine, actor_id: int) -> None:
    first, last = _day_bounds()
    # Outside the form so the sunset line below follows the chosen date at once.
    day = st.date_input("Date", value=first, min_value=first, max_value=last, key="create_day")
    sunset = ui.run_action(forecast.sunset_for, engine, day)
    with st.form("create_session"):
        start = st.time_input("Start", value=_DEFAULT_START, step=_STEP_S, key="create_start")
        if sunset is not None:
            st.caption(f"Sunset {fmt_time(sunset)}: sessions must end by then")
        duration = st.selectbox("Duration (minutes)", options=list(config.DURATIONS),
                                key="create_duration")
        capacity = st.number_input("Capacity", min_value=config.CAPACITY_MIN,
                                   max_value=config.CAPACITY_MAX, value=4, step=1,
                                   key="create_capacity")
        level = st.selectbox("Level", options=list(Level),
                             format_func=lambda lvl: lvl.value.capitalize(), key="create_level")
        submitted = st.form_submit_button("Create session", type="primary")
    if submitted:
        _finish(ui.run_action(
            sessions.create_session, engine, actor_id, day, start, int(duration),
            int(capacity), level.value,
        ))


def _upcoming(engine, actor_id: int) -> None:
    st.subheader("Upcoming sessions")
    result = ui.run_action(sessions.list_my_sessions, engine, actor_id)
    if result is None:
        return
    if not result.ok:
        ui.show_result(result)
        return
    mine: list[SessionView] = result.data
    if not mine:
        ui.empty_state(_NO_UPCOMING, ":material/event_available:")
        return
    scheduled = [s for s in mine if s.status == SessionStatus.SCHEDULED]
    conditions = ui.run_action(forecast.conditions_for_sessions, engine, scheduled) or {}
    for session in mine:
        with ui.card():
            st.markdown(f"### {_when(session)}")
            ui.chip(session.level.value.capitalize(), "info")
            st.caption(f":material/groups: {_booked(session)}")
            if session.status != SessionStatus.SCHEDULED:
                ui.chip("Called off", "neutral")
                continue
            ui.badge(conditions.get(session.id, _NO_FORECAST))
            edit_col, delete_col, call_col = st.columns(3)
            edit_col.button("Edit", key=f"edit_{session.id}",
                            on_click=_open, args=(_EDIT_KEY, session))
            # The service has the full history (R2.11); this only hides the
            # button where it is certain to be refused.
            if session.booked_count == 0:
                delete_col.button("Delete", key=f"delete_{session.id}",
                                  on_click=_open, args=(_DELETE_KEY, session))
            call_col.button("Call off", key=f"call_off_{session.id}",
                            on_click=_open, args=(_CALL_OFF_KEY, session))


def main() -> None:
    """Draw the My sessions screen for the signed-in instructor.

    Rules: section 11 (My sessions), LU07, LU09, R2.1-R2.11, R8.1-R8.5.
    """
    engine = ui.get_engine()
    ui.inject_styles()
    actor = ui.current_actor(engine)
    if actor is None:
        st.stop()

    ui.page_header("My sessions", "What needs you first, then everything coming up.")
    if actor.role != Role.INSTRUCTOR:
        ui.empty_state(_INSTRUCTORS_ONLY, ":material/info:")
        return
    ui.show_result(st.session_state.pop(_RESULT_KEY, None))

    # Streamlit allows one open dialog per run, so the first pending one wins.
    for key, dialog in ((_CALL_OFF_KEY, _call_off_dialog), (_EDIT_KEY, _edit_dialog),
                        (_DELETE_KEY, _delete_dialog)):
        pending = st.session_state.get(key)
        if pending:
            dialog(engine, actor.id, pending)
            break

    _decisions(engine, actor.id)
    _upcoming(engine, actor.id)
    # Secondary: creating is deliberate, so it never competes with a decision.
    with st.expander("Create a session"):
        _create_form(engine, actor.id)
    ui.footer_credit()


main()
