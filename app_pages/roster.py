"""Roster screen: one session's booked students and waitlist, attendance, CSV and call-off.

Every decision comes from lineup.services; this page only draws what they
return and hands each action to ui.run_action and ui.show_result. The services
check permissions and the time again, so the page's own checks only choose
what to draw.

Rules: section 11 (Roster), LU12, R8.1, R9.1-R9.3, R12.7, R12.8.
"""

from __future__ import annotations

import streamlit as st

from lineup import ui
from lineup.models import Attendance, CallOffCategory, SessionStatus, SessionView
from lineup.services import attendance, sessions
from lineup.timeutil import fmt_dt, fmt_time, utcnow

# Results survive the rerun that redraws the roster after an action.
_RESULTS_KEY = "roster_results"
_CALL_OFF_KEY = "roster_call_off"

_MARKS = {Attendance.ATTENDED.value: "Attended", Attendance.NO_SHOW.value: "No-show"}
_CATEGORIES = {
    CallOffCategory.CONDITIONS.value: "Conditions",
    CallOffCategory.INSTRUCTOR_UNAVAILABLE.value: "Instructor unavailable",
    CallOffCategory.OTHER.value: "Other",
}
_NO_SESSIONS = "No sessions in the last 7 days or coming up."
# Member 3's call_off is a stub until the Sessions lane builds it; its
# docstring says so, which lets this page switch the button on by itself.
_CALL_OFF_READY = "Stub" not in (sessions.call_off.__doc__ or "")


def _finish(results: list) -> None:
    # None entries mean run_action already showed the error; keep those on screen.
    shown = [r for r in results if r is not None]
    if not shown:
        return
    st.session_state[_RESULTS_KEY] = shown
    st.rerun()


def _label(session: SessionView) -> str:
    called_off = " (called off)" if session.status == SessionStatus.CALLED_OFF else ""
    return (f"{fmt_dt(session.starts_at)} · {session.level.value.capitalize()} · "
            f"{session.instructor_name}{called_off}")


def _booked(rows: list[dict]) -> None:
    """Show the booked students with level, attended Beginner count and attendance.

    Rules: section 11 (Roster), R3.6, R9.2.
    """
    st.subheader(f"Booked ({len(rows)})")
    if not rows:
        st.info("Nobody is booked yet.")
        return
    # st.dataframe draws every cell as plain text, so names are never markup.
    st.dataframe(
        [{"Student": r["name"], "Email": r["email"], "Level": r["level"].capitalize(),
          "Beginner sessions attended": r["beginner_attended"],
          "Attendance": _MARKS.get(r["attendance"], "—")} for r in rows],
        hide_index=True, width="stretch",
    )


def _waitlist(rows: list[dict]) -> None:
    """Show the waitlist, first joiner first.

    Rules: R4.2, section 11 (Roster).
    """
    st.subheader(f"Waitlist ({len(rows)})")
    if not rows:
        st.caption("Nobody is waiting.")
        return
    st.markdown("\n".join(
        f"{n}. {ui.plain(w['name'])} · joined {fmt_dt(w['joined_at'])}"
        for n, w in enumerate(rows, start=1)
    ))


def _attendance(engine, actor_id: int, session: SessionView, rows: list[dict]) -> None:
    """Show one Attended/No-show choice per student once the session has started.

    Rules: R9.1, R9.2, R9.3.
    """
    st.subheader("Attendance")
    if session.status == SessionStatus.CALLED_OFF:
        st.info("Attendance is closed: this session was called off.")
        return
    if utcnow() < session.starts_at:
        st.info(f"Attendance opens at {fmt_time(session.starts_at)}.")
        return
    if not rows:
        st.caption("Nobody to mark.")
        return
    with st.form(f"attendance_{session.id}"):
        choices = {}
        for r in rows:
            options = list(_MARKS)
            # Widget labels are read as Markdown, so the typed name is escaped.
            choices[r["booking_id"]] = (r["attendance"], st.radio(
                ui.plain(r["name"]), options, format_func=_MARKS.get, horizontal=True,
                index=options.index(r["attendance"]) if r["attendance"] in options else None,
                key=f"mark_{r['booking_id']}",
            ))
        if st.form_submit_button("Save attendance", type="primary"):
            changed = [(b, new) for b, (old, new) in choices.items()
                       if new is not None and new != old]
            if not changed:
                st.info("Nothing to save: no attendance changed.")
                return
            _finish([ui.run_action(attendance.mark_attendance, engine, actor_id, b, new)
                     for b, new in changed])


@st.dialog("Call off this session")
def _call_off_dialog(engine, actor_id: int, session: SessionView) -> None:
    """Ask for the category and a reason, then call the session off for everyone.

    Rules: R8.1, R8.2.
    """
    st.write(_label(session))
    category = st.selectbox("Category", list(_CATEGORIES), format_func=_CATEGORIES.get)
    reason = st.text_area("Reason (3-200 characters)", max_chars=200)
    cancel_col, confirm_col = st.columns(2)
    if cancel_col.button("Cancel", key="call_off_cancel"):
        st.session_state.pop(_CALL_OFF_KEY, None)
        st.rerun()
    if confirm_col.button("Call off", type="primary", key="call_off_confirm"):
        result = ui.run_action(sessions.call_off, engine, actor_id, session.id, category, reason)
        if result is not None:
            st.session_state.pop(_CALL_OFF_KEY, None)
            _finish([result])


def _actions(engine, actor_id: int, session: SessionView) -> None:
    """Offer the roster CSV and, for a scheduled session, Call off.

    Rules: R8.1, R12.7, R12.8.
    """
    csv_col, call_off_col = st.columns(2)
    exported = ui.run_action(attendance.roster_csv, engine, actor_id, session.id)
    if exported is not None and exported.ok:
        csv_col.download_button(
            "Download roster CSV", exported.data, mime="text/csv",
            file_name=f"roster-{session.starts_at:%Y%m%d-%H%M}.csv",
        )
    elif exported is not None:
        ui.show_result(exported)
    if session.status == SessionStatus.CALLED_OFF:
        return
    if call_off_col.button("Call off", disabled=not _CALL_OFF_READY):
        st.session_state[_CALL_OFF_KEY] = session.id
    if not _CALL_OFF_READY:
        call_off_col.caption("Call-off isn't available yet (Sessions lane).")
    if st.session_state.get(_CALL_OFF_KEY) == session.id:
        _call_off_dialog(engine, actor_id, session)


def main() -> None:
    """Draw the Roster screen for an instructor's own sessions or any session for an admin.

    Rules: section 11 (Roster), LU12.
    """
    engine = ui.get_engine()
    actor = ui.current_actor(engine)
    if actor is None:
        st.stop()

    st.title("Roster")
    for result in st.session_state.pop(_RESULTS_KEY, []):
        ui.show_result(result)

    listed = ui.run_action(attendance.roster_sessions, engine, actor.id)
    if listed is None:
        return
    if not listed.ok:
        ui.show_result(listed)
        return
    if not listed.data:
        st.info(_NO_SESSIONS)
        return
    by_id = {s.id: s for s in listed.data}
    session_id = st.selectbox("Session", list(by_id), format_func=lambda i: _label(by_id[i]),
                              key="roster_session")

    loaded = ui.run_action(attendance.roster, engine, actor.id, session_id)
    if loaded is None:
        return
    if not loaded.ok:
        ui.show_result(loaded)
        return
    session = loaded.data["session"]
    _booked(loaded.data["booked"])
    _waitlist(loaded.data["waitlist"])
    _attendance(engine, actor.id, session, loaded.data["booked"])
    _actions(engine, actor.id, session)


main()
