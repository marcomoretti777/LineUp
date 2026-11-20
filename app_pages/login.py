"""Log in and sign up, the only screen a visitor can reach.

After a successful attempt the page keeps nothing but the member id in
st.session_state (spec section 12, Login).

Rules: R1.1, R1.2, R1.3, R1.4, section 11, section 12.
"""

import streamlit as st

from lineup import auth, ui
from lineup.logic import accounts
from lineup.services import members

engine = ui.get_engine()

st.title("LineUp")
st.caption("Surf sessions for the campus surf club.")

log_in_tab, sign_up_tab = st.tabs(["Log in", "Sign up"])


def _start_session(auth_result) -> None:
    """Link the auth account to a profile and keep only the member id.

    Rules: R1.4, section 12 (login).
    """
    linked = ui.run_action(
        members.login_member,
        engine,
        auth_result.data["auth_user_id"],
        auth_result.data["email"],
        auth_result.data.get("full_name"),
    )
    if linked is None:
        return
    if not linked.ok:
        ui.show_result(linked)
        return
    st.session_state["member_id"] = linked.data
    st.rerun()


with log_in_tab:
    with st.form("log_in"):
        email = st.text_input("Email", key="log_in_email",
                              placeholder=f"name@{accounts.ALLOWED_EMAIL_DOMAIN}")
        password = st.text_input("Password", type="password", key="log_in_password")
        submitted = st.form_submit_button("Log in", type="primary")

    if submitted:
        result = ui.run_action(auth.sign_in, email, password)
        if result is not None:
            if result.ok:
                _start_session(result)
            else:
                # Under the fields, not as a banner, so the eye lands on them.
                st.error(result.message)

with sign_up_tab:
    with st.form("sign_up"):
        new_name = st.text_input("Full name", key="sign_up_name")
        name_slot = st.empty()
        new_email = st.text_input("Email", key="sign_up_email",
                                  placeholder=f"name@{accounts.ALLOWED_EMAIL_DOMAIN}")
        email_slot = st.empty()
        new_password = st.text_input("Password", type="password", key="sign_up_password")
        confirmation = st.text_input("Repeat password", type="password",
                                     key="sign_up_confirmation")
        password_slot = st.empty()
        st.caption(f"Club members sign up with their @{accounts.ALLOWED_EMAIL_DOMAIN} address.")
        created = st.form_submit_button("Sign up", type="primary")

    if created:
        # Each field reports its own problem before anything is sent.
        problems = {
            name_slot: accounts.validate_name(new_name),
            email_slot: accounts.validate_email(new_email),
            password_slot: accounts.validate_password(new_password, confirmation),
        }
        for slot, refusal in problems.items():
            if refusal:
                slot.error(refusal.message)

        if not any(problems.values()):
            result = ui.run_action(auth.sign_up, new_email, new_password, new_name)
            if result is not None:
                if not result.ok:
                    email_slot.error(result.message)
                elif result.data.get("needs_confirmation"):
                    st.info(
                        "Account created. Confirm your email address, then log in."
                    )
                else:
                    _start_session(result)
