"""Credits screen: balance, packs, request and withdraw a pack, statement and its CSV.

Every decision comes from lineup.services.credits; this page only draws what
the services return and hands each action to ui.run_action and ui.show_result.

Rules: section 11 (Credits), LU10, R10.1-R10.4, R10.7, R12.7, R12.8.
"""

from __future__ import annotations

import streamlit as st

from lineup import ui
from lineup.logic.reports import to_csv
from lineup.models import RequestStatus
from lineup.services import credits
from lineup.timeutil import fmt_dt, to_local

# The last action's Result survives the rerun that refreshes balance and lists.
_RESULT_KEY = "credits_result"
_PAY_HINT = "Pay by MB WAY to the club number, then enter the reference"
_STATEMENT_HEADER = ("created_at", "kind", "delta", "ref", "note", "balance")


def _finish(result) -> None:
    # None means run_action already showed the error; a rerun would wipe it.
    if result is None:
        return
    st.session_state[_RESULT_KEY] = result
    st.rerun()


def _packs(packs: list[dict]) -> None:
    """Show one card per pack: credits, price and price per credit.

    Rules: R10.1.
    """
    st.subheader("Packs")
    for column, pack in zip(st.columns(len(packs) or 1), packs, strict=False):
        with column, ui.card():
            st.markdown(f"**{ui.plain(pack['name'])}**")
            st.write(f"{pack['credits']} credit{'' if pack['credits'] == 1 else 's'}")
            st.metric("Price", pack["price"], label_visibility="collapsed")
            st.caption(f"{pack['price_per_credit']} per credit")


def _request_form(engine, actor_id: int, packs: list[dict]) -> None:
    """Show the request form; the service checks the reference and the one-pending rule.

    Rules: R10.2, R10.3.
    """
    st.subheader("Request a pack")
    st.caption(_PAY_HINT)
    names = {p["id"]: f"{p['name']} · {p['price']}" for p in packs}
    with st.form("credits_request", clear_on_submit=False):
        pack_id = st.selectbox("Pack", options=list(names), format_func=names.get)
        reference = st.text_input("Payment reference", max_chars=40,
                                  placeholder="MBWAY 912")
        if st.form_submit_button("Request pack", type="primary"):
            _finish(ui.run_action(credits.request_pack, engine, actor_id, pack_id, reference))


def _pending(engine, actor_id: int, requests: list[dict]) -> None:
    """Show the pending request, if any, with a Withdraw button.

    Rules: R10.2, R10.4.
    """
    pending = [r for r in requests if r["status"] == RequestStatus.PENDING.value]
    if not pending:
        st.caption("No pending request.")
        return
    request = pending[0]
    with ui.card():
        st.markdown(f"**Pending:** {ui.plain(request['pack_name'])} · {request['price']}")
        st.caption(f"Requested {fmt_dt(request['created_at'])}")
        st.text(f"Reference: {request['payment_ref']}")
        if st.button("Withdraw", key=f"withdraw_{request['id']}"):
            _finish(ui.run_action(credits.withdraw_request, engine, actor_id, request["id"]))


def _local(dt) -> str:
    return to_local(dt).strftime("%Y-%m-%d %H:%M")


def _statement(rows: list[dict]) -> None:
    """Show the statement table, newest first, and its formula-safe CSV download.

    Rules: R10.7, R10.8, R12.7, R12.8.
    """
    if not rows:
        ui.empty_state("No credit movements yet.", ":material/receipt_long:")
        return
    # st.dataframe draws every cell as plain text, so notes are never markup.
    st.dataframe(
        [{"When": fmt_dt(r["created_at"]), "Kind": r["kind"], "Change": r["delta"],
          "Reference": r["ref"], "Balance after": r["balance"]} for r in rows],
        hide_index=True, width="stretch",
    )
    csv_text = to_csv(_STATEMENT_HEADER, [
        (_local(r["created_at"]), r["kind"], r["delta"], r["ref"], r["note"], r["balance"])
        for r in rows
    ])
    st.download_button("Download statement CSV", csv_text.encode("utf-8"),
                       file_name="lineup-statement.csv", mime="text/csv")


def main() -> None:
    """Draw the Credits screen for the signed-in student.

    Rules: section 11 (Credits), LU10.
    """
    engine = ui.get_engine()
    ui.inject_styles()
    actor = ui.current_actor(engine)
    if actor is None:
        st.stop()

    ui.page_header("Credits", "One credit books one session.")
    ui.show_result(st.session_state.pop(_RESULT_KEY, None))

    statement = ui.run_action(credits.statement, engine, actor.id)
    if statement is None:
        return
    if not statement.ok:
        ui.show_result(statement)
        return
    balance = statement.data["balance"]
    st.metric("Balance", f"{balance} credit{'' if balance == 1 else 's'}")

    packs = ui.run_action(credits.list_packs, engine) or []
    _packs(packs)

    requests = ui.run_action(credits.my_requests, engine, actor.id)
    if requests is not None and not requests.ok:
        ui.show_result(requests)
    else:
        _request_form(engine, actor.id, packs)
        _pending(engine, actor.id, requests.data if requests else [])

    # Secondary detail: the statement is reference, not the next step.
    with st.expander("Statement"):
        _statement(statement.data["rows"])


main()
