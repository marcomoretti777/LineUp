"""Inbox screen: the member's notifications, newest first, with Mark all as read.

Every decision comes from lineup.services.notifications; this page only draws
the list and hands the action to ui.run_action and ui.show_result.

Rules: section 11 (Inbox), LU11, R11.3.
"""

from __future__ import annotations

import streamlit as st

from lineup import ui
from lineup.services import notifications
from lineup.timeutil import fmt_dt

# The Result survives the rerun that refreshes the list and the sidebar count.
_RESULT_KEY = "inbox_result"
_EMPTY = "No notifications yet."


def _item(item: dict) -> None:
    """Draw one notification: Lisbon time, then the message, bold while unread.

    Rules: section 11 (Inbox), section 12 (output safety).
    """
    text = ui.plain(item["message"])
    unread = item["read_at"] is None
    with st.container(border=True):
        st.caption(fmt_dt(item["created_at"]) + (" · Unread" if unread else ""))
        st.markdown(f"**{text}**" if unread else text)


def main() -> None:
    """Draw the Inbox screen for the signed-in member.

    Rules: section 11 (Inbox), LU11, R11.3.
    """
    engine = ui.get_engine()
    actor = ui.current_actor(engine)
    if actor is None:
        st.stop()

    st.title("Inbox")
    ui.show_result(st.session_state.pop(_RESULT_KEY, None))

    listed = ui.run_action(notifications.list_notifications, engine, actor.id)
    if listed is None:
        return
    if not listed.ok:
        ui.show_result(listed)
        return
    items = listed.data
    if not items:
        st.info(_EMPTY)
        return

    if any(item["read_at"] is None for item in items):
        if st.button("Mark all as read", type="primary"):
            result = ui.run_action(notifications.mark_all_read, engine, actor.id)
            if result is not None:
                st.session_state[_RESULT_KEY] = result
                # A full rerun redraws the list in plain text and the sidebar count.
                st.rerun()

    for item in items:
        _item(item)


main()
