"""Credit requests screen: the pending queue with Approve and Reject, and the decided history.

Every decision comes from lineup.services.credits; this page only draws what
the service returns and hands each action to ui.run_action and ui.show_result.

Rules: section 11 (Credit requests), LU11, R10.5, R10.6.
"""

from __future__ import annotations

import streamlit as st

from lineup import ui
from lineup.logic.credits import fmt_eur
from lineup.services import credits
from lineup.timeutil import fmt_dt

# The last action's Result survives the rerun that refreshes the queue; the
# reject key holds the request whose dialog is open.
_RESULT_KEY = "admin_requests_result"
_REJECT_KEY = "admin_requests_reject"
_STATUS = {"approved": "Approved", "rejected": "Rejected", "withdrawn": "Withdrawn"}


def _finish(result) -> None:
    # None means run_action already showed the error; a rerun would wipe it.
    if result is None:
        return
    st.session_state.pop(_REJECT_KEY, None)
    st.session_state[_RESULT_KEY] = result
    st.rerun()


@st.dialog("Reject this request", on_dismiss=lambda: st.session_state.pop(_REJECT_KEY, None))
def _reject_dialog(engine, actor_id: int, request: dict) -> None:
    """Ask for the rejection note; the service checks its length.

    Rules: R10.5.
    """
    st.write(f"{ui.plain(request['member_name'])} · {ui.plain(request['pack_name'])} · "
             f"{fmt_eur(request['price_cents'])}")
    note = st.text_area("Note to the student (3-200 characters)", max_chars=200)
    cancel_col, reject_col = st.columns(2)
    if cancel_col.button("Cancel", key="reject_cancel"):
        st.session_state.pop(_REJECT_KEY, None)
        st.rerun()
    if reject_col.button("Reject", type="primary", key="reject_confirm"):
        result = ui.run_action(credits.reject_request, engine, actor_id, request["id"], note)
        if result is not None and not result.ok:
            # Keep the dialog open so the admin can fix the note.
            ui.show_result(result)
            return
        _finish(result)


def _approve(engine, actor_id: int, request_id: int) -> None:
    """Approve one request from a button callback and keep its Result for the next run.

    A callback runs even when the request has left the queue since this tab
    last drew it, so a stale tab's click still reaches the service and gets
    "Nothing changed" instead of being dropped silently.

    Rules: R10.5, R10.6.
    """
    result = ui.run_action(credits.approve_request, engine, actor_id, request_id)
    if result is not None:
        st.session_state[_RESULT_KEY] = result


def _pending_card(engine, actor_id: int, request: dict) -> None:
    """Draw one pending request with Approve and Reject.

    Rules: R10.5, R10.6.
    """
    with st.container(border=True):
        st.markdown(f"**{ui.plain(request['member_name'])}** · "
                    f"{ui.plain(request['member_email'])}")
        st.write(f"{ui.plain(request['pack_name'])} · {request['credits']} "
                 f"credit{'' if request['credits'] == 1 else 's'} · "
                 f"{fmt_eur(request['price_cents'])}")
        st.text(f"Reference: {request['payment_ref']}")
        st.caption(f"Requested {fmt_dt(request['created_at'])}")
        approve_col, reject_col = st.columns(2)
        approve_col.button("Approve", type="primary", key=f"approve_{request['id']}",
                           on_click=_approve, args=(engine, actor_id, request["id"]))
        if reject_col.button("Reject", key=f"reject_{request['id']}"):
            st.session_state[_REJECT_KEY] = request["id"]


def _pending(engine, actor_id: int) -> None:
    """Show the pending queue, oldest first, and the reject dialog when one is open.

    Rules: R10.5, section 11 (Credit requests).
    """
    listed = ui.run_action(credits.pending_requests, engine, actor_id)
    if listed is None:
        return
    if not listed.ok:
        ui.show_result(listed)
        return
    if not listed.data:
        ui.empty_state("No pending requests.", ":material/inbox:")
        return
    for request in listed.data:
        _pending_card(engine, actor_id, request)
    open_id = st.session_state.get(_REJECT_KEY)
    chosen = next((r for r in listed.data if r["id"] == open_id), None)
    if chosen is not None:
        _reject_dialog(engine, actor_id, chosen)


def _history(engine, actor_id: int) -> None:
    """Show the most recent decided requests, newest decision first.

    Rules: R10.4, R10.5.
    """
    listed = ui.run_action(credits.decided_requests, engine, actor_id)
    if listed is None:
        return
    if not listed.ok:
        ui.show_result(listed)
        return
    if not listed.data:
        ui.empty_state("No decided requests yet.", ":material/history:")
        return
    # st.dataframe draws every cell as plain text, so names and notes are never markup.
    st.dataframe(
        [{"Student": r["member_name"], "Pack": r["pack_name"],
          "Amount": fmt_eur(r["price_cents"]), "Status": _STATUS.get(r["status"], r["status"]),
          "Decided": fmt_dt(r["decided_at"]) if r["decided_at"] else "—",
          "Note": r["decision_note"] or ""} for r in listed.data],
        hide_index=True, width="stretch",
    )


def main() -> None:
    """Draw the Credit requests screen for an admin.

    Rules: section 11 (Credit requests), LU11.
    """
    engine = ui.get_engine()
    ui.inject_styles()
    actor = ui.current_actor(engine)
    if actor is None:
        st.stop()

    ui.page_header("Credit requests", "Oldest first, so nobody waits twice as long.")
    ui.show_result(st.session_state.pop(_RESULT_KEY, None))

    pending_tab, history_tab = st.tabs(["Pending", "History"])
    with pending_tab:
        _pending(engine, actor.id)
    with history_tab:
        _history(engine, actor.id)


main()
